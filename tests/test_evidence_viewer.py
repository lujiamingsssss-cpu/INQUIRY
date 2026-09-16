import hashlib
import json
from pathlib import Path

import fitz
import pytest

from chemical_trade_copilot import evidence_viewer, pdf_pages
from chemical_trade_copilot.evidence_viewer import (
    build_zoomable_page_html,
    render_citation_page,
)
from chemical_trade_copilot.inquiry_analysis import SourceCitation


def _write_pdf(path: Path, pages: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open() as document:
        for number in range(1, pages + 1):
            page = document.new_page()
            page.insert_text((72, 72), f"EPON Resin 8280 physical page {number}")
        document.save(path)


def _materials(tmp_path: Path) -> tuple[Path, Path]:
    product = tmp_path / "EPON Resin 8280"
    tds = product / "TDS - Hexion EPON Resin 8280 - Rev 2016.pdf"
    sds = product / "SDS - Westlake EPON Resin 8280 - US EN - 2022.pdf"
    _write_pdf(tds, pages=3)
    _write_pdf(sds, pages=1)
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            [
                {
                    "product": "EPON Resin 8280",
                    "relative_path": "EPON Resin 8280/TDS - Hexion EPON Resin 8280 - Rev 2016.pdf",
                    "document_type": "TDS",
                    "date_revision": "Reissued 2005 · footer revision 2016",
                    "jurisdiction": "Technical data sheet · jurisdiction not stated",
                    "enabled": True,
                    "sha256": hashlib.sha256(tds.read_bytes()).hexdigest(),
                    "source_url": "https://manufacturer.example/tds.pdf",
                    "acquired_on": "2026-07-28",
                },
                {
                    "product": "EPON Resin 8280",
                    "relative_path": "EPON Resin 8280/SDS - Westlake EPON Resin 8280 - US EN - 2022.pdf",
                    "document_type": "SDS",
                    "date_revision": "2022",
                    "jurisdiction": "United States · English SDS",
                    "enabled": True,
                    "sha256": hashlib.sha256(sds.read_bytes()).hexdigest(),
                    "source_url": "https://manufacturer.example/sds.pdf",
                    "acquired_on": "2026-07-28",
                },
            ]
        ),
        encoding="utf-8",
    )
    return tmp_path, catalog


def test_render_citation_page_uses_only_exact_approved_product_document(
    tmp_path: Path,
) -> None:
    root, catalog = _materials(tmp_path)
    citation = SourceCitation(
        product="EPON Resin 8280",
        source_file="TDS - Hexion EPON Resin 8280 - Rev 2016.pdf",
        page_number=3,
    )

    rendered = render_citation_page(citation, root, catalog)

    assert rendered.product == "EPON Resin 8280"
    assert rendered.source_file == "TDS - Hexion EPON Resin 8280 - Rev 2016.pdf"
    assert rendered.page_number == 3
    assert rendered.date_revision == "Reissued 2005 · footer revision 2016"
    assert rendered.jurisdiction == "Technical data sheet · jurisdiction not stated"
    assert rendered.png_bytes.startswith(b"\x89PNG\r\n\x1a\n")


def test_render_citation_page_rejects_unknown_file(tmp_path: Path) -> None:
    root, catalog = _materials(tmp_path)
    citation = SourceCitation(
        product="EPON Resin 8280",
        source_file="TDS - Not Approved.pdf",
        page_number=1,
    )

    with pytest.raises(ValueError, match="not an approved source document"):
        render_citation_page(citation, root, catalog)


def test_render_citation_page_rejects_wrong_product_for_valid_file(
    tmp_path: Path,
) -> None:
    root, catalog = _materials(tmp_path)
    citation = SourceCitation(
        product="Different Product",
        source_file="TDS - Hexion EPON Resin 8280 - Rev 2016.pdf",
        page_number=1,
    )

    with pytest.raises(ValueError, match="not an approved source document"):
        render_citation_page(citation, root, catalog)


def test_render_citation_page_rejects_page_outside_pdf(tmp_path: Path) -> None:
    root, catalog = _materials(tmp_path)
    citation = SourceCitation(
        product="EPON Resin 8280",
        source_file="TDS - Hexion EPON Resin 8280 - Rev 2016.pdf",
        page_number=4,
    )

    with pytest.raises(ValueError, match="outside the source PDF"):
        render_citation_page(citation, root, catalog)


@pytest.mark.parametrize("mutation", ["replace", "delete"])
def test_verified_pdf_snapshot_survives_file_change_and_next_open_fails_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    root, catalog = _materials(tmp_path)
    source_path = (
        root
        / "EPON Resin 8280"
        / "TDS - Hexion EPON Resin 8280 - Rev 2016.pdf"
    )
    citation = SourceCitation(
        product="EPON Resin 8280",
        source_file=source_path.name,
        page_number=3,
    )
    approved = pdf_pages.load_approved_pdf(
        citation.product,
        citation.source_file,
        root,
        catalog,
    )
    verified_bytes = approved.pdf_bytes
    source_path.unlink()
    if mutation == "replace":
        _write_pdf(source_path, pages=1)

    rendered = evidence_viewer.render_approved_citation_page(citation, approved)

    assert approved.pdf_bytes == verified_bytes
    assert approved.page_count == 3
    assert rendered.page_number == 3
    assert rendered.png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    expected_error = ValueError if mutation == "replace" else FileNotFoundError
    expected_message = "hash mismatch" if mutation == "replace" else "Missing approved PDF"
    with pytest.raises(expected_error, match=expected_message):
        pdf_pages.load_approved_pdf(
            citation.product,
            citation.source_file,
            root,
            catalog,
        )


def test_zoomable_html_has_click_and_bounded_zoom_controls() -> None:
    html = build_zoomable_page_html(
        b"\x89PNG\r\n\x1a\nimage",
        alt_text='TDS page <3> "verified"',
        source_metadata="EPON Resin 8280 · Rev 2016 · Physical page 3",
    )

    assert 'aria-label="Zoom in"' in html
    assert 'aria-label="Zoom out"' in html
    assert 'aria-label="Reset zoom"' in html
    assert 'aria-label="Open source page viewer"' in html
    assert 'data-min-zoom="50"' in html
    assert 'data-max-zoom="250"' in html
    assert 'data-zoom-step="25"' in html
    assert "image.addEventListener(\"click\"" in html
    assert "TDS page &lt;3&gt; &quot;verified&quot;" in html
    assert "EPON Resin 8280 · Rev 2016 · Physical page 3" in html
    assert "data:image/png;base64," in html
