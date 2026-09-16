import argparse
import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .evaluation import load_golden_cases, validate_golden_gate
from .index_lifecycle import rebuild_index, rollback_index
from .materials import (
    ApprovedDocument,
    discover_documents,
    load_material_catalog,
    material_catalog_fingerprint,
)
from .pdf_pages import PageRecord, extract_all_pages
from .inquiry_analysis import (
    DeepSeekInquiryAnalyzer,
    DeepSeekJsonClient,
    InquiryRetrievalPlanner,
)
from .retrieval import PageIndex, SearchResult
from .workflow import analyze_inquiry


DEFAULT_CATALOG = Path("materials_catalog.json")
DEFAULT_GOLDEN_CASES = Path("tests/fixtures/golden_retrieval_cases.json")


class _MetadataOnlyEmbedder:
    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        raise RuntimeError("Status inspection must not calculate embeddings")


def _result_dict(result: SearchResult) -> dict[str, Any]:
    value = asdict(result)
    value.pop("page_text", None)
    value["source_path"] = str(value["source_path"])
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Page-level evidence retrieval")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command, help_text in (
        ("ingest", "Safely rebuild and replace the local page index"),
        ("rebuild", "Build, validate, and switch a staged page index"),
    ):
        rebuild = subparsers.add_parser(command, help=help_text)
        rebuild.add_argument("--materials-root", type=Path, required=True)
        rebuild.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
        rebuild.add_argument("--database", type=Path, default=Path(".chroma"))
        rebuild.add_argument(
            "--golden-cases", type=Path, default=DEFAULT_GOLDEN_CASES
        )

    preflight = subparsers.add_parser(
        "preflight", help="Validate the approved material catalog without indexing"
    )
    preflight.add_argument("--materials-root", type=Path, required=True)
    preflight.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)

    status = subparsers.add_parser("status", help="Show catalog and index status")
    status.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    status.add_argument("--database", type=Path, default=Path(".chroma"))

    verify = subparsers.add_parser("verify", help="Run the golden retrieval gate")
    verify.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    verify.add_argument("--database", type=Path, default=Path(".chroma"))
    verify.add_argument("--golden-cases", type=Path, default=DEFAULT_GOLDEN_CASES)

    rollback = subparsers.add_parser(
        "rollback", help="Swap the active index with its retained backup"
    )
    rollback.add_argument("--database", type=Path, default=Path(".chroma"))

    query = subparsers.add_parser("query", help="Retrieve traceable source pages")
    query.add_argument("inquiry")
    query.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    query.add_argument("--database", type=Path, default=Path(".chroma"))
    query.add_argument("--limit", type=int, default=5)

    analyze = subparsers.add_parser(
        "analyze", help="Create a cited chemical export inquiry analysis"
    )
    analyze.add_argument("inquiry")
    analyze.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    analyze.add_argument("--database", type=Path, default=Path(".chroma"))
    analyze.add_argument("--limit", type=int, default=3)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "preflight":
        sources, pages, _ = _preflight(args.materials_root, args.catalog)
        _print_summary(sources, len(pages), state="preflight_passed")
        return

    if args.command in {"ingest", "rebuild"}:
        sources, pages, catalog_fingerprint = _preflight(
            args.materials_root, args.catalog
        )
        products = {source.product for source in sources}

        def build(staging: Path) -> None:
            index = PageIndex(staging)
            try:
                index.replace(pages, catalog_fingerprint=catalog_fingerprint)
            finally:
                index.close()

        def validate(staging: Path) -> None:
            index = PageIndex(staging)
            try:
                stored_pages = index.pages()
                if _page_integrity_fingerprint(stored_pages) != (
                    _page_integrity_fingerprint(pages)
                ):
                    raise ValueError(
                        "Staged index pages do not match preflight extraction"
                    )
                index.assert_catalog_fingerprint(catalog_fingerprint)
                validate_golden_gate(
                    load_golden_cases(args.golden_cases),
                    index,
                    enabled_products=products,
                    maximum_rank=3,
                )
            finally:
                index.close()

        rebuild_index(args.database, build=build, validate=validate)
        _print_summary(sources, len(pages), state="active_index_replaced")
        return

    if args.command == "verify":
        catalog = load_material_catalog(args.catalog)
        products = {entry.product for entry in catalog if entry.enabled}
        index = PageIndex(args.database)
        try:
            index.assert_catalog_fingerprint(material_catalog_fingerprint(catalog))
            evaluation = validate_golden_gate(
                load_golden_cases(args.golden_cases),
                index,
                enabled_products=products,
                maximum_rank=3,
            )
        finally:
            index.close()
        print(
            json.dumps(
                {
                    "state": "golden_gate_passed",
                    "answerable_cases": evaluation.answerable_cases,
                    "hit_at_3": evaluation.hit_at_k[3],
                },
                ensure_ascii=False,
            )
        )
        return

    if args.command == "status":
        catalog = load_material_catalog(args.catalog)
        enabled = [entry for entry in catalog if entry.enabled]
        active_index = args.database.is_dir()
        pages: list[PageRecord] = []
        if active_index:
            index = PageIndex(args.database, embedder=_MetadataOnlyEmbedder())
            try:
                pages = index.pages()
                index_catalog_fingerprint = index.catalog_fingerprint
            finally:
                index.close()
        else:
            index_catalog_fingerprint = None
        recovery_required = any(
            args.database.with_name(f"{args.database.name}.{suffix}").exists()
            for suffix in ("staging", "rollback", "recovery")
        )
        print(
            json.dumps(
                {
                    "state": _catalog_index_state(
                        enabled,
                        pages,
                        active_index=active_index,
                        index_catalog_fingerprint=index_catalog_fingerprint,
                        recovery_required=recovery_required,
                    ),
                    "enabled_products": sorted({entry.product for entry in enabled}),
                    "enabled_documents": len(enabled),
                    "active_index": active_index,
                    "rollback_available": args.database.with_name(
                        f"{args.database.name}.backup"
                    ).is_dir(),
                },
                ensure_ascii=False,
            )
        )
        return

    if args.command == "rollback":
        rollback_index(args.database)
        print(json.dumps({"state": "rollback_complete"}))
        return

    if args.command == "query":
        catalog_fingerprint = material_catalog_fingerprint(
            load_material_catalog(args.catalog)
        )
        with PageIndex(args.database) as index:
            index.assert_catalog_fingerprint(catalog_fingerprint)
            results = index.query(args.inquiry, limit=args.limit)
        payload = {
            "inquiry": args.inquiry,
            "results": [_result_dict(item) for item in results],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY must be set in the process environment")
    client = DeepSeekJsonClient(
        api_key,
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"),
    )
    catalog_fingerprint = material_catalog_fingerprint(
        load_material_catalog(args.catalog)
    )
    with PageIndex(args.database) as index:
        index.assert_catalog_fingerprint(catalog_fingerprint)
        analysis = analyze_inquiry(
            args.inquiry,
            index=index,
            planner=InquiryRetrievalPlanner(client),
            analyzer=DeepSeekInquiryAnalyzer(client),
            limit=args.limit,
        )
    print(analysis.model_dump_json(indent=2))


def _preflight(materials_root: Path, catalog_path: Path):
    catalog = load_material_catalog(catalog_path)
    sources = discover_documents(materials_root, catalog)
    return sources, extract_all_pages(sources), material_catalog_fingerprint(catalog)


def _print_summary(sources, indexed_pages: int, *, state: str) -> None:
    print(
        json.dumps(
            {
                "state": state,
                "products": sorted({source.product for source in sources}),
                "documents": len(sources),
                "indexed_pages": indexed_pages,
            },
            ensure_ascii=False,
        )
    )


def _catalog_index_state(
    enabled: list[ApprovedDocument],
    pages: list[PageRecord],
    *,
    active_index: bool,
    index_catalog_fingerprint: str | None,
    recovery_required: bool,
) -> str:
    if recovery_required:
        return "index_recovery_required"
    if not active_index:
        return "index_missing"
    if index_catalog_fingerprint != material_catalog_fingerprint(enabled):
        return "index_catalog_mismatch"
    expected_documents = {(entry.product, entry.relative_path.name) for entry in enabled}
    indexed_documents = {(page.product, page.source_file) for page in pages}
    if expected_documents != indexed_documents:
        return "index_catalog_mismatch"
    return "ready"


def _page_integrity_fingerprint(pages: list[PageRecord]) -> str:
    records = sorted(
        (
            page.product,
            page.doc_type,
            page.source_file,
            str(page.source_path.resolve()),
            page.page_number,
            hashlib.sha256(page.text.encode("utf-8")).hexdigest(),
        )
        for page in pages
    )
    return hashlib.sha256(
        json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


if __name__ == "__main__":
    main()
