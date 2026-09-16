from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import cast

import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .embeddings import Embedder, MultilingualE5Embedder
from .materials import DocumentType
from .pdf_pages import PageRecord


@dataclass(frozen=True, slots=True)
class SearchResult:
    text: str
    product: str
    doc_type: str
    source_file: str
    source_path: Path
    page_number: int
    distance: float
    page_text: str = ""
    date_revision: str = "not_recorded"
    jurisdiction: str = "not_recorded"


@dataclass(frozen=True, slots=True)
class _PageChunk:
    text: str
    page: PageRecord
    chunk_number: int


class PageIndex:
    def __init__(
        self,
        database_path: Path,
        *,
        embedder: Embedder | None = None,
        collection_name: str = "page_evidence",
    ) -> None:
        database_path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(database_path))
        self._collection = self._client.get_or_create_collection(collection_name)
        self._closed = False
        self._embedder = embedder or MultilingualE5Embedder()
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=900,
            chunk_overlap=150,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    def replace(
        self, pages: list[PageRecord], *, catalog_fingerprint: str | None = None
    ) -> None:
        chunks = self._chunks(pages)
        embeddings = (
            self._embedder.encode([f"passage: {chunk.text}" for chunk in chunks])
            if chunks
            else []
        )
        current = self._collection.get(include=[])["ids"]
        if current:
            self._collection.delete(ids=current)
        if not chunks:
            return
        self._collection.add(
            ids=[self._id(chunk) for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            embeddings=embeddings,
            metadatas=[
                {
                    "product": chunk.page.product,
                    "doc_type": chunk.page.doc_type,
                    "source_file": chunk.page.source_file,
                    "source_path": str(chunk.page.source_path),
                    "page_number": chunk.page.page_number,
                    "chunk_number": chunk.chunk_number,
                    "page_text": chunk.page.text,
                    "date_revision": chunk.page.date_revision,
                    "jurisdiction": chunk.page.jurisdiction,
                }
                for chunk in chunks
            ],
        )
        if catalog_fingerprint is not None:
            self._collection.modify(metadata={"catalog_fingerprint": catalog_fingerprint})

    @property
    def catalog_fingerprint(self) -> str | None:
        metadata = self._collection.metadata or {}
        value = metadata.get("catalog_fingerprint")
        return str(value) if value else None

    def assert_catalog_fingerprint(self, expected: str) -> None:
        if self.catalog_fingerprint != expected:
            raise ValueError("Index catalog fingerprint does not match approved catalog")

    def query(
        self,
        inquiry: str,
        *,
        limit: int = 5,
        doc_types: tuple[DocumentType, ...] | None = None,
    ) -> list[SearchResult]:
        if not inquiry.strip():
            raise ValueError("Inquiry must not be empty")
        if limit < 1:
            raise ValueError("Limit must be at least 1")
        if doc_types is not None and not doc_types:
            raise ValueError("Document type filter must not be empty")
        if self._collection.count() == 0:
            return []

        where = _document_type_filter(doc_types)
        result = self._collection.query(
            query_embeddings=self._embedder.encode([f"query: {inquiry.strip()}"]),
            n_results=min(limit * 4, self._collection.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        documents = result["documents"][0]
        metadatas = result["metadatas"][0]
        distances = result["distances"][0]
        results: list[SearchResult] = []
        seen_pages: set[tuple[str, int]] = set()
        for document, metadata, distance in zip(documents, metadatas, distances):
            page_key = (str(metadata["source_path"]), int(metadata["page_number"]))
            if page_key in seen_pages:
                continue
            seen_pages.add(page_key)
            results.append(
                SearchResult(
                    text=document,
                    product=str(metadata["product"]),
                    doc_type=str(metadata["doc_type"]),
                    source_file=str(metadata["source_file"]),
                    source_path=Path(str(metadata["source_path"])),
                    page_number=int(metadata["page_number"]),
                    distance=float(distance),
                    page_text="",
                    date_revision=str(metadata.get("date_revision", "not_recorded")),
                    jurisdiction=str(metadata.get("jurisdiction", "not_recorded")),
                )
            )
            if len(results) == limit:
                break
        return results

    def pages(
        self, *, doc_types: tuple[DocumentType, ...] | None = None
    ) -> list[PageRecord]:
        if doc_types is not None and not doc_types:
            raise ValueError("Document type filter must not be empty")
        stored = self._collection.get(
            where=_document_type_filter(doc_types),
            include=["metadatas"],
        )
        pages: dict[tuple[str, int], PageRecord] = {}
        for metadata in stored["metadatas"] or []:
            page_text = metadata.get("page_text")
            if not page_text:
                raise ValueError("Index must be rebuilt with full-page evidence metadata")
            key = (str(metadata["source_path"]), int(metadata["page_number"]))
            pages[key] = PageRecord(
                text=str(page_text),
                product=str(metadata["product"]),
                doc_type=cast(DocumentType, str(metadata["doc_type"])),
                source_file=str(metadata["source_file"]),
                source_path=Path(str(metadata["source_path"])),
                page_number=int(metadata["page_number"]),
                date_revision=str(metadata.get("date_revision", "not_recorded")),
                jurisdiction=str(metadata.get("jurisdiction", "not_recorded")),
            )
        return sorted(
            pages.values(),
            key=lambda page: (page.product, page.source_file, page.page_number),
        )

    def close(self) -> None:
        """Release Chroma resources before a Windows directory switch."""
        if self._closed:
            return
        self._client.close()
        self._closed = True

    def __enter__(self) -> "PageIndex":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _chunks(self, pages: list[PageRecord]) -> list[_PageChunk]:
        return [
            _PageChunk(text=text, page=page, chunk_number=chunk_number)
            for page in pages
            for chunk_number, text in enumerate(self._splitter.split_text(page.text), start=1)
        ]

    @staticmethod
    def _id(chunk: _PageChunk) -> str:
        identity = (
            f"{chunk.page.source_path}|{chunk.page.page_number}|{chunk.chunk_number}"
        ).encode("utf-8")
        return sha256(identity).hexdigest()


def _document_type_filter(
    doc_types: tuple[DocumentType, ...] | None,
) -> dict[str, object] | None:
    if not doc_types:
        return None
    if len(doc_types) == 1:
        return {"doc_type": doc_types[0]}
    return {"doc_type": {"$in": list(doc_types)}}
