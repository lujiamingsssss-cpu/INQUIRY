import hashlib
import json
from pathlib import Path

import fitz
import pytest

from chemical_trade_copilot import pdf_pages
from chemical_trade_copilot.materials import SourceDocument
from chemical_trade_copilot.pdf_pages import extract_pages


def _write_pdf(path: Path, *, pages: int = 3) -> None:
    document = fitz.open()
    first = document.new_page()
    first.insert_text((72, 72), "EPON Resin 8280 high solids coatings")
    if pages >= 2:
        document.new_page()  # Deliberately blank; page numbering must remain physical.
    if pages >= 3:
        third = document.new_page()
        third.insert_text((72, 72), "Heat Deflection Temperature 156 C")
    document.save(path)
    document.close()


def test_extract_pages_preserves_physical_page_and_source_metadata(tmp_path: Path) -> None:
    path = tmp_path / "TDS - EPON Resin 8280.pdf"
    _write_pdf(path)
    source = SourceDocument(
        path=path,
        product="EPON Resin 8280",
        doc_type="TDS",
        date_revision="2016",
        jurisdiction="Technical data sheet · jurisdiction not stated",
        sha256="0" * 64,
        source_url="https://manufacturer.example/tds.pdf",
        acquired_on="2026-07-28",
    )

    pages = extract_pages(source)

    assert [page.page_number for page in pages] == [1, 3]
    assert pages[0].source_file == path.name
    assert pages[0].product == "EPON Resin 8280"
    assert pages[0].doc_type == "TDS"
    assert pages[0].date_revision == "2016"
    assert pages[0].jurisdiction == "Technical data sheet · jurisdiction not stated"
    assert "high solids coatings" in pages[0].text
    assert "156 C" in pages[1].text


def _catalog_entry(
    relative_path: str,
    *,
    product: str = "Controlled Product",
    enabled: bool = True,
    sha256: str = "0" * 64,
) -> dict[str, object]:
    return {
        "product": product,
        "relative_path": relative_path,
        "document_type": "TDS",
        "date_revision": "2026",
        "jurisdiction": "not recorded",
        "enabled": enabled,
        "sha256": sha256,
        "source_url": "urn:legacy:test",
        "acquired_on": "2026-07-30",
    }


def _write_catalog(path: Path, entries: list[dict[str, object]]) -> None:
    path.write_text(json.dumps(entries), encoding="utf-8")


def test_approved_pdf_path_returns_the_one_enabled_catalog_pdf(tmp_path: Path) -> None:
    materials_root = tmp_path / "materials"
    approved = materials_root / "Controlled Product" / "TDS - Controlled.pdf"
    approved.parent.mkdir(parents=True)
    _write_pdf(approved)
    catalog_path = tmp_path / "catalog.json"
    _write_catalog(
        catalog_path,
        [
            _catalog_entry(
                "Controlled Product/TDS - Controlled.pdf",
                sha256=hashlib.sha256(approved.read_bytes()).hexdigest(),
            )
        ],
    )

    result = pdf_pages.approved_pdf_path(
        "Controlled Product",
        "TDS - Controlled.pdf",
        materials_root,
        catalog_path,
    )

    assert result == approved.resolve()


@pytest.mark.parametrize(
    ("entries", "expected_exception"),
    [
        ([], ValueError),
        (
            [_catalog_entry("Controlled Product/TDS - Controlled.pdf", enabled=False)],
            ValueError,
        ),
        (
            [
                _catalog_entry("first/TDS - Controlled.pdf"),
                _catalog_entry("second/TDS - Controlled.pdf"),
            ],
            ValueError,
        ),
    ],
)
def test_approved_pdf_path_rejects_missing_disabled_or_duplicate_catalog_matches(
    tmp_path: Path,
    entries: list[dict[str, object]],
    expected_exception: type[Exception],
) -> None:
    materials_root = tmp_path / "materials"
    materials_root.mkdir()
    catalog_path = tmp_path / "catalog.json"
    _write_catalog(catalog_path, entries)

    with pytest.raises(expected_exception):
        pdf_pages.approved_pdf_path(
            "Controlled Product",
            "TDS - Controlled.pdf",
            materials_root,
            catalog_path,
        )


def test_approved_pdf_path_rejects_missing_file_and_path_escape(tmp_path: Path) -> None:
    materials_root = tmp_path / "materials"
    materials_root.mkdir()
    catalog_path = tmp_path / "catalog.json"
    _write_catalog(
        catalog_path,
        [_catalog_entry("Controlled Product/TDS - Missing.pdf")],
    )

    with pytest.raises(FileNotFoundError):
        pdf_pages.approved_pdf_path(
            "Controlled Product",
            "TDS - Missing.pdf",
            materials_root,
            catalog_path,
        )

    outside = tmp_path / "TDS - Outside.pdf"
    _write_pdf(outside)
    _write_catalog(
        catalog_path,
        [
            _catalog_entry(
                "../TDS - Outside.pdf",
                sha256=hashlib.sha256(outside.read_bytes()).hexdigest(),
            )
        ],
    )

    with pytest.raises(ValueError, match="outside materials root"):
        pdf_pages.approved_pdf_path(
            "Controlled Product",
            "TDS - Outside.pdf",
            materials_root,
            catalog_path,
        )


def test_approved_pdf_path_rejects_caller_supplied_paths(tmp_path: Path) -> None:
    materials_root = tmp_path / "materials"
    approved = materials_root / "Controlled Product" / "TDS - Controlled.pdf"
    approved.parent.mkdir(parents=True)
    _write_pdf(approved)
    catalog_path = tmp_path / "catalog.json"
    _write_catalog(
        catalog_path,
        [
            _catalog_entry(
                "Controlled Product/TDS - Controlled.pdf",
                sha256=hashlib.sha256(approved.read_bytes()).hexdigest(),
            )
        ],
    )

    with pytest.raises(ValueError):
        pdf_pages.approved_pdf_path(
            "Controlled Product",
            str(tmp_path / "attacker" / approved.name),
            materials_root,
            catalog_path,
        )


def test_approved_pdf_path_rejects_non_pdf_and_absolute_catalog_paths(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    materials_root.mkdir()
    non_pdf = materials_root / "Controlled Product" / "TDS - Controlled.txt"
    non_pdf.parent.mkdir()
    non_pdf.write_text("not a PDF", encoding="utf-8")
    catalog_path = tmp_path / "catalog.json"
    _write_catalog(
        catalog_path,
        [_catalog_entry("Controlled Product/TDS - Controlled.txt")],
    )

    with pytest.raises(ValueError, match="must be a PDF"):
        pdf_pages.approved_pdf_path(
            "Controlled Product",
            "TDS - Controlled.txt",
            materials_root,
            catalog_path,
        )

    absolute_pdf = tmp_path / "TDS - Absolute.pdf"
    _write_pdf(absolute_pdf)
    _write_catalog(
        catalog_path,
        [
            _catalog_entry(
                str(absolute_pdf),
                sha256=hashlib.sha256(absolute_pdf.read_bytes()).hexdigest(),
            )
        ],
    )

    with pytest.raises(ValueError, match="outside materials root"):
        pdf_pages.approved_pdf_path(
            "Controlled Product",
            absolute_pdf.name,
            materials_root,
            catalog_path,
        )


def test_load_approved_pdf_rejects_catalog_hash_mismatch(tmp_path: Path) -> None:
    materials_root = tmp_path / "materials"
    approved = materials_root / "Controlled Product" / "TDS - Controlled.pdf"
    approved.parent.mkdir(parents=True)
    _write_pdf(approved, pages=1)
    expected_hash = hashlib.sha256(approved.read_bytes()).hexdigest()
    catalog_path = tmp_path / "catalog.json"
    _write_catalog(
        catalog_path,
        [
            _catalog_entry(
                "Controlled Product/TDS - Controlled.pdf",
                sha256=expected_hash,
            )
        ],
    )
    approved.unlink()
    _write_pdf(approved, pages=3)

    with pytest.raises(ValueError, match="hash mismatch"):
        pdf_pages.approved_pdf_path(
            "Controlled Product",
            approved.name,
            materials_root,
            catalog_path,
        )
