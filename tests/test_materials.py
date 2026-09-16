import hashlib
import json
from pathlib import Path

import fitz
import pytest

from chemical_trade_copilot.materials import (
    ApprovedDocument,
    discover_documents,
    enabled_catalog_snapshot,
    load_material_catalog,
)


def _write_pdf(path: Path, product: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), f"Approved document for {product}")
        document.save(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _entry(
    relative_path: str,
    product: str,
    doc_type: str,
    sha256: str,
    *,
    enabled: bool = True,
    document_identity: str | None = None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "product": product,
        "relative_path": relative_path,
        "document_type": doc_type,
        "date_revision": "2026-07-28",
        "jurisdiction": "United States · English",
        "enabled": enabled,
        "sha256": sha256,
        "source_url": "https://manufacturer.example/document.pdf",
        "acquired_on": "2026-07-28",
    }
    if document_identity is not None:
        entry["document_identity"] = document_identity
    return entry


def _write_catalog(path: Path, entries: list[dict[str, object]]) -> Path:
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def test_discover_documents_uses_only_enabled_catalog_entries(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    tds_path = root / "Product A" / "TDS - Product A.pdf"
    sds_path = root / "Product A" / "SDS - Product A.pdf"
    tds_hash = _write_pdf(tds_path, "Product A")
    sds_hash = _write_pdf(sds_path, "Product A")
    catalog_path = _write_catalog(
        tmp_path / "catalog.json",
        [
            _entry("Product A/TDS - Product A.pdf", "Product A", "TDS", tds_hash),
            _entry("Product A/SDS - Product A.pdf", "Product A", "SDS", sds_hash),
            _entry(
                "Product A/TDS - Product A old.pdf",
                "Product A",
                "TDS",
                "0" * 64,
                enabled=False,
            ),
        ],
    )

    documents = discover_documents(root, load_material_catalog(catalog_path))

    assert [(doc.product, doc.doc_type, doc.path.name) for doc in documents] == [
        ("Product A", "SDS", "SDS - Product A.pdf"),
        ("Product A", "TDS", "TDS - Product A.pdf"),
    ]
    assert documents[0].date_revision == "2026-07-28"
    assert documents[0].jurisdiction == "United States · English"


def test_enabled_catalog_snapshot_is_sorted_metadata_only() -> None:
    catalog = (
        ApprovedDocument(
            product="B",
            relative_path=Path("B/TDS.pdf"),
            document_type="TDS",
            date_revision="2026-01-01",
            jurisdiction="not stated",
            enabled=True,
            sha256="b" * 64,
            source_url="https://example.com/b.pdf",
            acquired_on="2026-01-01",
            document_identity="B",
        ),
        ApprovedDocument(
            product="A",
            relative_path=Path("A/SDS.pdf"),
            document_type="SDS",
            date_revision="2026-01-01",
            jurisdiction="not stated",
            enabled=False,
            sha256="a" * 64,
            source_url="https://example.com/a.pdf",
            acquired_on="2026-01-01",
            document_identity="A",
        ),
    )

    assert enabled_catalog_snapshot(catalog) == (("B/TDS.pdf", "b" * 64),)


def test_catalog_requires_all_traceability_metadata(tmp_path: Path) -> None:
    incomplete = _entry("Product A/TDS.pdf", "Product A", "TDS", "0" * 64)
    del incomplete["source_url"]
    catalog_path = _write_catalog(tmp_path / "catalog.json", [incomplete])

    with pytest.raises(ValueError, match="source_url"):
        load_material_catalog(catalog_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("acquired_on", "28-07-2026", "acquired_on"),
        ("source_url", "https://", "source_url"),
    ],
)
def test_catalog_validates_traceability_metadata_format(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    entry = _entry("Product A/TDS.pdf", "Product A", "TDS", "0" * 64)
    entry[field] = value
    catalog_path = _write_catalog(tmp_path / "catalog.json", [entry])

    with pytest.raises(ValueError, match=message):
        load_material_catalog(catalog_path)


def test_discover_documents_rejects_catalog_without_enabled_documents(
    tmp_path: Path,
) -> None:
    catalog_path = _write_catalog(tmp_path / "catalog.json", [])

    with pytest.raises(ValueError, match="at least one enabled"):
        discover_documents(tmp_path / "materials", load_material_catalog(catalog_path))


def test_discover_documents_rejects_path_outside_materials_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside.pdf"
    digest = _write_pdf(outside, "Product A")
    root = tmp_path / "materials"
    sds_hash = _write_pdf(root / "Product A" / "SDS - Product A.pdf", "Product A")
    catalog_path = _write_catalog(
        tmp_path / "catalog.json",
        [
            _entry("../outside.pdf", "Product A", "TDS", digest),
            _entry(
                "Product A/SDS - Product A.pdf", "Product A", "SDS", sds_hash
            ),
        ],
    )

    with pytest.raises(ValueError, match="outside materials root"):
        discover_documents(root, load_material_catalog(catalog_path))


def test_discover_documents_rejects_hash_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    _write_pdf(root / "Product A" / "TDS - Product A.pdf", "Product A")
    sds_hash = _write_pdf(root / "Product A" / "SDS - Product A.pdf", "Product A")
    catalog_path = _write_catalog(
        tmp_path / "catalog.json",
        [
            _entry("Product A/TDS - Product A.pdf", "Product A", "TDS", "0" * 64),
            _entry(
                "Product A/SDS - Product A.pdf", "Product A", "SDS", sds_hash
            ),
        ],
    )

    with pytest.raises(ValueError, match="hash mismatch"):
        discover_documents(root, load_material_catalog(catalog_path))


def test_discover_documents_rejects_duplicate_enabled_hashes(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    tds_path = root / "Product A" / "TDS - Product A.pdf"
    digest = _write_pdf(tds_path, "Product A")
    sds_path = root / "Product A" / "SDS - Product A.pdf"
    sds_path.write_bytes(tds_path.read_bytes())
    catalog_path = _write_catalog(
        tmp_path / "catalog.json",
        [
            _entry("Product A/TDS - Product A.pdf", "Product A", "TDS", digest),
            _entry("Product A/SDS - Product A.pdf", "Product A", "SDS", digest),
        ],
    )

    with pytest.raises(ValueError, match="duplicate enabled document hash"):
        discover_documents(root, load_material_catalog(catalog_path))


def test_discover_documents_rejects_wrong_product_attribution(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    path = root / "Product A" / "TDS - Product A.pdf"
    digest = _write_pdf(path, "Different Product")
    sds_hash = _write_pdf(root / "Product A" / "SDS - Product A.pdf", "Product A")
    catalog_path = _write_catalog(
        tmp_path / "catalog.json",
        [
            _entry("Product A/TDS - Product A.pdf", "Product A", "TDS", digest),
            _entry(
                "Product A/SDS - Product A.pdf", "Product A", "SDS", sds_hash
            ),
        ],
    )

    with pytest.raises(ValueError, match="does not identify product"):
        discover_documents(root, load_material_catalog(catalog_path))


def test_discover_documents_accepts_explicit_document_identity_alias(
    tmp_path: Path,
) -> None:
    root = tmp_path / "materials"
    tds_hash = _write_pdf(
        root / "BAER XP9500" / "TDS - BAER XP9500.pdf", "BAER XP-9500"
    )
    sds_hash = _write_pdf(
        root / "BAER XP9500" / "SDS - BAER XP9500.pdf", "XP-9500, XP-2500"
    )
    catalog_path = _write_catalog(
        tmp_path / "catalog.json",
        [
            _entry(
                "BAER XP9500/TDS - BAER XP9500.pdf",
                "BAER XP9500",
                "TDS",
                tds_hash,
            ),
            _entry(
                "BAER XP9500/SDS - BAER XP9500.pdf",
                "BAER XP9500",
                "SDS",
                sds_hash,
                document_identity="XP-9500",
            ),
        ],
    )

    documents = discover_documents(root, load_material_catalog(catalog_path))

    assert len(documents) == 2
    assert {document.product for document in documents} == {"BAER XP9500"}


def test_discover_documents_requires_one_enabled_tds_and_sds_per_product(
    tmp_path: Path,
) -> None:
    root = tmp_path / "materials"
    path = root / "Product A" / "TDS.pdf"
    digest = _write_pdf(path, "Product A")
    catalog_path = _write_catalog(
        tmp_path / "catalog.json",
        [_entry("Product A/TDS.pdf", "Product A", "TDS", digest)],
    )

    with pytest.raises(ValueError, match="exactly one enabled TDS and SDS"):
        discover_documents(root, load_material_catalog(catalog_path))
