import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlparse

import fitz


DocumentType = Literal["TDS", "SDS"]


@dataclass(frozen=True, slots=True)
class ApprovedDocument:
    product: str
    relative_path: Path
    document_type: DocumentType
    date_revision: str
    jurisdiction: str
    enabled: bool
    sha256: str
    source_url: str
    acquired_on: str
    document_identity: str


@dataclass(frozen=True, slots=True)
class SourceDocument:
    path: Path
    product: str
    doc_type: DocumentType
    date_revision: str
    jurisdiction: str
    sha256: str
    source_url: str
    acquired_on: str


def load_material_catalog(path: Path) -> tuple[ApprovedDocument, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Material catalog must be a JSON list")

    required = {
        "product",
        "relative_path",
        "document_type",
        "date_revision",
        "jurisdiction",
        "enabled",
        "sha256",
        "source_url",
        "acquired_on",
    }
    entries: list[ApprovedDocument] = []
    for position, raw in enumerate(payload, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Material catalog entry {position} must be an object")
        missing = sorted(required - raw.keys())
        if missing:
            raise ValueError(
                f"Material catalog entry {position} is missing: {', '.join(missing)}"
            )
        doc_type = str(raw["document_type"]).upper()
        if doc_type not in {"TDS", "SDS"}:
            raise ValueError(f"Unsupported document_type: {doc_type!r}")
        digest = str(raw["sha256"]).casefold()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"Invalid sha256 in material catalog entry {position}")
        if type(raw["enabled"]) is not bool:
            raise ValueError(f"enabled must be a boolean in entry {position}")
        source_url = str(raw["source_url"]).strip()
        parsed_url = urlparse(source_url)
        valid_web_url = parsed_url.scheme in {"https", "http"} and bool(
            parsed_url.hostname
        )
        valid_legacy_urn = source_url.startswith("urn:legacy:") and bool(
            source_url.removeprefix("urn:legacy:").strip()
        )
        if not (valid_web_url or valid_legacy_urn):
            raise ValueError(
                f"source_url must be HTTP(S) or an explicit legacy URN in entry {position}"
            )
        values = {
            field: str(raw[field]).strip()
            for field in (
                "product",
                "relative_path",
                "date_revision",
                "jurisdiction",
                "acquired_on",
            )
        }
        document_identity = str(
            raw.get("document_identity", values["product"])
        ).strip()
        if not document_identity:
            raise ValueError(
                f"Material catalog entry {position} has an empty document_identity"
            )
        empty = [field for field, value in values.items() if not value]
        if empty:
            raise ValueError(
                f"Material catalog entry {position} has empty fields: {', '.join(empty)}"
            )
        try:
            date.fromisoformat(values["acquired_on"])
        except ValueError as error:
            raise ValueError(
                f"acquired_on must be an ISO date in entry {position}"
            ) from error
        entries.append(
            ApprovedDocument(
                product=values["product"],
                relative_path=Path(values["relative_path"]),
                document_type=cast(DocumentType, doc_type),
                date_revision=values["date_revision"],
                jurisdiction=values["jurisdiction"],
                enabled=cast(bool, raw["enabled"]),
                sha256=digest,
                source_url=source_url,
                acquired_on=values["acquired_on"],
                document_identity=document_identity,
            )
        )
    return tuple(entries)


def evidence_scope_caption(catalog_path: Path) -> str:
    products = sorted(
        {entry.product for entry in load_material_catalog(catalog_path) if entry.enabled},
        key=str.casefold,
    )
    if not products:
        scope = "no enabled products"
    elif len(products) == 1:
        scope = products[0]
    else:
        scope = f"{', '.join(products[:-1])} and {products[-1]}"
    return (
        f"Evidence scope: approved {scope} documents only. "
        "Document dates and jurisdictions remain limitations."
    )


def material_catalog_fingerprint(
    catalog: tuple[ApprovedDocument, ...] | list[ApprovedDocument],
) -> str:
    enabled = [entry for entry in catalog if entry.enabled]
    payload = [
        {
            "product": entry.product,
            "relative_path": entry.relative_path.as_posix(),
            "document_type": entry.document_type,
            "date_revision": entry.date_revision,
            "jurisdiction": entry.jurisdiction,
            "sha256": entry.sha256,
            "source_url": entry.source_url,
            "acquired_on": entry.acquired_on,
            "document_identity": entry.document_identity,
        }
        for entry in sorted(
            enabled,
            key=lambda item: (
                item.product.casefold(),
                item.document_type,
                item.relative_path.as_posix().casefold(),
            ),
        )
    ]
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def enabled_catalog_snapshot(
    catalog: tuple[ApprovedDocument, ...] | list[ApprovedDocument],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (entry.relative_path.as_posix(), entry.sha256)
            for entry in catalog
            if entry.enabled
        )
    )


def discover_documents(
    materials_root: Path, catalog: tuple[ApprovedDocument, ...] | list[ApprovedDocument]
) -> list[SourceDocument]:
    """Preflight and return only enabled documents from the approved catalog."""
    enabled = [entry for entry in catalog if entry.enabled]
    if not enabled:
        raise ValueError("Material catalog must contain at least one enabled document")
    _validate_enabled_versions(enabled)
    resolved_root = materials_root.resolve()
    documents: list[SourceDocument] = []
    hashes: dict[str, Path] = {}
    paths: set[Path] = set()

    for entry in enabled:
        if entry.relative_path.is_absolute():
            raise ValueError(
                f"Catalog document is outside materials root: {entry.relative_path}"
            )
        path = (resolved_root / entry.relative_path).resolve()
        try:
            path.relative_to(resolved_root)
        except ValueError as error:
            raise ValueError(f"Catalog document is outside materials root: {path}") from error
        if path in paths:
            raise ValueError(f"Duplicate enabled document path: {entry.relative_path}")
        paths.add(path)
        if not path.is_file():
            raise FileNotFoundError(f"Missing approved document: {path}")
        if path.suffix.casefold() != ".pdf":
            raise ValueError(f"Approved document must be a PDF: {path.name}")
        if not path.name.upper().startswith(f"{entry.document_type} -"):
            raise ValueError(
                f"Approved filename must start with {entry.document_type} -: {path.name}"
            )
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_hash != entry.sha256:
            raise ValueError(f"Approved document hash mismatch: {entry.relative_path}")
        if actual_hash in hashes:
            raise ValueError(
                "Found duplicate enabled document hash: "
                f"{hashes[actual_hash]} and {entry.relative_path}"
            )
        hashes[actual_hash] = entry.relative_path
        text = _read_pdf_text(path)
        if _normalized_identity(entry.document_identity) not in _normalized_identity(text):
            raise ValueError(
                f"Approved document does not identify product {entry.product!r}: {path.name}"
            )
        documents.append(
            SourceDocument(
                path=path,
                product=entry.product,
                doc_type=entry.document_type,
                date_revision=entry.date_revision,
                jurisdiction=entry.jurisdiction,
                sha256=entry.sha256,
                source_url=entry.source_url,
                acquired_on=entry.acquired_on,
            )
        )
    return sorted(
        documents,
        key=lambda item: (item.product.casefold(), item.path.name.casefold()),
    )


def _validate_enabled_versions(entries: list[ApprovedDocument]) -> None:
    products = {entry.product for entry in entries}
    for product in products:
        counts = {
            doc_type: sum(
                entry.product == product and entry.document_type == doc_type
                for entry in entries
            )
            for doc_type in ("TDS", "SDS")
        }
        if counts != {"TDS": 1, "SDS": 1}:
            raise ValueError(
                f"Product {product!r} must have exactly one enabled TDS and SDS; "
                f"found {counts}"
            )


def _read_pdf_text(path: Path) -> str:
    try:
        with fitz.open(path) as document:
            if document.page_count < 1:
                raise ValueError(f"Approved PDF has no physical pages: {path.name}")
            text = "\n".join(page.get_text("text", sort=True) for page in document)
    except (fitz.FileDataError, RuntimeError) as error:
        raise ValueError(f"Approved PDF is unreadable: {path.name}") from error
    if not text.strip():
        raise ValueError(f"Approved PDF contains no extractable text: {path.name}")
    return text


def _normalized_identity(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())
