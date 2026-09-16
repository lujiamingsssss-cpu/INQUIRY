import hashlib
from dataclasses import dataclass
from pathlib import Path

import fitz

from .materials import DocumentType, SourceDocument, load_material_catalog


@dataclass(frozen=True, slots=True)
class PageRecord:
    text: str
    product: str
    doc_type: DocumentType
    source_file: str
    source_path: Path
    page_number: int
    date_revision: str = "not_recorded"
    jurisdiction: str = "not_recorded"


@dataclass(frozen=True, slots=True)
class ApprovedPdf:
    path: Path
    pdf_bytes: bytes
    product: str
    source_file: str
    date_revision: str
    jurisdiction: str
    sha256: str
    page_count: int


def extract_pages(source: SourceDocument) -> list[PageRecord]:
    """Extract non-empty pages while retaining the PDF's physical page number."""
    records: list[PageRecord] = []
    with fitz.open(source.path) as document:
        for zero_based_page, page in enumerate(document):
            text = page.get_text("text", sort=True).strip()
            if not text:
                continue
            records.append(
                PageRecord(
                    text=text,
                    product=source.product,
                    doc_type=source.doc_type,
                    source_file=source.path.name,
                    source_path=source.path.resolve(),
                    page_number=zero_based_page + 1,
                    date_revision=source.date_revision,
                    jurisdiction=source.jurisdiction,
                )
            )
    return records


def extract_all_pages(sources: list[SourceDocument]) -> list[PageRecord]:
    return [page for source in sources for page in extract_pages(source)]


def approved_pdf_path(
    product: str,
    source_file: str,
    materials_root: Path,
    catalog_path: Path,
) -> Path:
    """Resolve and verify one enabled catalog PDF, returning its controlled path."""
    return load_approved_pdf(
        product,
        source_file,
        materials_root,
        catalog_path,
    ).path


def load_approved_pdf(
    product: str,
    source_file: str,
    materials_root: Path,
    catalog_path: Path,
) -> ApprovedPdf:
    """Read one catalog-selected PDF once and return its verified byte snapshot."""
    requested_name = Path(source_file).name
    if requested_name != source_file:
        raise ValueError("Citation source_file must be a PDF basename")

    matches = [
        entry
        for entry in load_material_catalog(catalog_path)
        if entry.enabled
        and entry.product == product
        and entry.relative_path.name == requested_name
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Citation is not an approved source document: {source_file}"
        )

    entry = matches[0]
    if entry.relative_path.is_absolute():
        raise ValueError(f"Approved PDF is outside materials root: {entry.relative_path}")
    resolved_root = materials_root.resolve()
    approved_path = (resolved_root / entry.relative_path).resolve()
    try:
        approved_path.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(
            f"Approved PDF is outside materials root: {approved_path}"
        ) from error
    if approved_path.suffix.casefold() != ".pdf":
        raise ValueError(f"Approved document must be a PDF: {approved_path.name}")
    try:
        pdf_bytes = approved_path.read_bytes()
    except (FileNotFoundError, IsADirectoryError, PermissionError) as error:
        raise FileNotFoundError(f"Missing approved PDF: {approved_path}") from error
    actual_hash = hashlib.sha256(pdf_bytes).hexdigest()
    if actual_hash != entry.sha256:
        raise ValueError(f"Approved PDF hash mismatch: {entry.relative_path}")
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            page_count = document.page_count
    except (fitz.FileDataError, RuntimeError) as error:
        raise ValueError(f"Approved PDF is unreadable: {approved_path.name}") from error
    if page_count < 1:
        raise ValueError(f"Approved PDF has no physical pages: {approved_path.name}")
    return ApprovedPdf(
        path=approved_path,
        pdf_bytes=pdf_bytes,
        product=entry.product,
        source_file=entry.relative_path.name,
        date_revision=entry.date_revision,
        jurisdiction=entry.jurisdiction,
        sha256=entry.sha256,
        page_count=page_count,
    )
