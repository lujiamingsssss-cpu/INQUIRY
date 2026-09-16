from pathlib import Path

import pytest

from chemical_trade_copilot.cli import (
    _catalog_index_state,
    _page_integrity_fingerprint,
    _parser,
    _result_dict,
)
from chemical_trade_copilot.materials import ApprovedDocument
from chemical_trade_copilot.pdf_pages import PageRecord
from chemical_trade_copilot.retrieval import SearchResult


def test_ingest_cli_does_not_allow_product_override() -> None:
    parser = _parser()

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "ingest",
                "--materials-root",
                "G:/materials",
                "--product",
                "Unreviewed Product",
            ]
        )


def test_stage_five_admin_commands_share_catalog_and_index_arguments() -> None:
    parser = _parser()

    preflight = parser.parse_args(
        [
            "preflight",
            "--materials-root",
            "G:/materials",
            "--catalog",
            "approved.json",
        ]
    )
    rebuild = parser.parse_args(
        [
            "rebuild",
            "--materials-root",
            "G:/materials",
            "--catalog",
            "approved.json",
            "--database",
            "index",
            "--golden-cases",
            "golden.json",
        ]
    )
    status = parser.parse_args(
        [
            "status",
            "--catalog",
            "approved.json",
            "--database",
            "index",
        ]
    )
    rollback = parser.parse_args(["rollback", "--database", "index"])

    assert preflight.materials_root == Path("G:/materials")
    assert preflight.catalog == Path("approved.json")
    assert rebuild.golden_cases == Path("golden.json")
    assert status.catalog == Path("approved.json")
    assert status.database == Path("index")
    assert rollback.database == Path("index")


def test_analyze_cli_ranks_three_pages_by_default() -> None:
    args = _parser().parse_args(["analyze", "customer inquiry"])

    assert args.command == "analyze"
    assert args.inquiry == "customer inquiry"
    assert args.limit == 3


def test_query_result_json_keeps_full_page_text_internal() -> None:
    result = SearchResult(
        text="matched chunk",
        product="EPON Resin 8280",
        doc_type="TDS",
        source_file="TDS.pdf",
        source_path=Path("C:/TDS.pdf"),
        page_number=3,
        distance=0.1,
        page_text="full physical page",
    )

    payload = _result_dict(result)

    assert payload["text"] == "matched chunk"
    assert "page_text" not in payload


def test_status_detects_catalog_index_mismatch() -> None:
    approved = ApprovedDocument(
        product="BAER XP9500",
        relative_path=Path("BAER XP9500/TDS - BAER XP9500.pdf"),
        document_type="TDS",
        date_revision="Revision 09132018",
        jurisdiction="Technical data sheet · jurisdiction not stated",
        enabled=True,
        sha256="0" * 64,
        source_url="https://manufacturer.example/tds.pdf",
        acquired_on="2026-07-28",
        document_identity="BAER XP9500",
    )
    old_page = PageRecord(
        text="old evidence",
        product="EPON Resin 8280",
        doc_type="TDS",
        source_file="TDS - EPON Resin 8280.pdf",
        source_path=Path("G:/materials/EPON/TDS - EPON Resin 8280.pdf"),
        page_number=1,
    )

    assert _catalog_index_state(
        [approved],
        [old_page],
        active_index=True,
        index_catalog_fingerprint=None,
        recovery_required=False,
    ) == (
        "index_catalog_mismatch"
    )


def test_page_integrity_fingerprint_detects_same_count_content_change() -> None:
    first = PageRecord(
        text="first content",
        product="Product",
        doc_type="TDS",
        source_file="TDS - Product.pdf",
        source_path=Path("G:/materials/Product/TDS - Product.pdf"),
        page_number=1,
    )
    changed = PageRecord(
        text="changed content",
        product=first.product,
        doc_type=first.doc_type,
        source_file=first.source_file,
        source_path=first.source_path,
        page_number=first.page_number,
    )

    assert _page_integrity_fingerprint([first]) != _page_integrity_fingerprint([changed])


def test_status_reports_recovery_remnants_before_ready() -> None:
    assert _catalog_index_state(
        [],
        [],
        active_index=True,
        index_catalog_fingerprint=None,
        recovery_required=True,
    ) == "index_recovery_required"
