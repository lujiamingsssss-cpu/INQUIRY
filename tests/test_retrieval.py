from collections.abc import Sequence
from pathlib import Path

import pytest

from chemical_trade_copilot.pdf_pages import PageRecord
from chemical_trade_copilot.retrieval import PageIndex


class KeywordEmbedder:
    """Small deterministic test double; production uses multilingual E5."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        values = list(texts)
        self.calls.append(values)
        return [
            [
                float("temperature" in value.lower() or "\u8010\u9ad8\u6e29" in value),
                float("safety" in value.lower() or "\u5b89\u5168" in value),
            ]
            for value in values
        ]


def _page(text: str, page_number: int, doc_type: str = "TDS") -> PageRecord:
    return PageRecord(
        text=text,
        product="EPON Resin 8280",
        doc_type=doc_type,
        source_file=f"{doc_type} - EPON Resin 8280.pdf",
        source_path=Path(f"C:/{doc_type}.pdf"),
        page_number=page_number,
    )


def test_index_and_query_returns_traceable_page(tmp_path: Path) -> None:
    embedder = KeywordEmbedder()
    index = PageIndex(tmp_path / "chroma", embedder=embedder)
    index.replace(
        [
            _page("passage about general coating use", 1),
            _page("heat deflection temperature 156 C with MPDA cure", 3),
            _page("safety and first aid information", 4, "SDS"),
        ]
    )

    results = index.query("\u8010\u9ad8\u6e29\u6d82\u6599\u73af\u6c27\u6811\u8102", limit=1)

    assert len(results) == 1
    assert results[0].product == "EPON Resin 8280"
    assert results[0].source_file == "TDS - EPON Resin 8280.pdf"
    assert results[0].page_number == 3
    assert results[0].distance == 0.0
    assert embedder.calls[0][0].startswith("passage: ")
    assert embedder.calls[-1] == ["query: \u8010\u9ad8\u6e29\u6d82\u6599\u73af\u6c27\u6811\u8102"]


def test_long_page_is_chunked_without_losing_page_metadata(tmp_path: Path) -> None:
    embedder = KeywordEmbedder()
    index = PageIndex(tmp_path / "chroma", embedder=embedder)
    long_page = _page(("general coating information " * 100) + "heat deflection temperature 156 C", 3)

    index.replace([long_page])

    passage_batch = embedder.calls[0]
    assert len(passage_batch) > 1
    assert any("heat deflection temperature 156 C" in text for text in passage_batch)
    result = index.query("temperature", limit=1)[0]
    assert result.page_number == 3
    assert result.source_file == "TDS - EPON Resin 8280.pdf"
    assert result.text != long_page.text
    assert result.page_text == ""


def test_trailing_use_limitation_is_not_buried_in_company_boilerplate(
    tmp_path: Path,
) -> None:
    embedder = KeywordEmbedder()
    index = PageIndex(tmp_path / "chroma", embedder=embedder)
    limitation = "PRODUCT USE: FOR EXPERIMENTAL USE ONLY"
    page = _page(("general company identification " * 35) + limitation, 1, "SDS")

    index.replace([page])

    limitation_chunks = [
        text for text in embedder.calls[0] if limitation in text
    ]
    assert limitation_chunks
    assert min(map(len, limitation_chunks)) < 600


def test_query_can_limit_evidence_to_tds_pages(tmp_path: Path) -> None:
    embedder = KeywordEmbedder()
    index = PageIndex(tmp_path / "chroma", embedder=embedder)
    index.replace(
        [
            _page("general coating use", 1),
            _page("safety information", 2, "SDS"),
        ]
    )

    results = index.query("safety", limit=2, doc_types=("TDS",))

    assert results
    assert all(result.doc_type == "TDS" for result in results)


def test_pages_returns_each_full_physical_page_once(tmp_path: Path) -> None:
    embedder = KeywordEmbedder()
    index = PageIndex(tmp_path / "chroma", embedder=embedder)
    long_page = _page(
        ("general coating information " * 100)
        + "heat deflection temperature 156 C",
        3,
    )
    index.replace([long_page, _page("safety information", 1, "SDS")])

    pages = index.pages(doc_types=("TDS",))

    assert len(pages) == 1
    assert pages[0] == long_page


def test_close_releases_persistent_database_for_directory_switch(tmp_path: Path) -> None:
    database = tmp_path / "chroma"
    index = PageIndex(database, embedder=KeywordEmbedder())
    index.replace([_page("general coating use", 1)])

    index.close()
    switched = tmp_path / "chroma.backup"
    database.rename(switched)

    assert switched.is_dir()


def test_close_releases_database_after_reopen_for_validation(tmp_path: Path) -> None:
    database = tmp_path / "chroma"
    writer = PageIndex(database, embedder=KeywordEmbedder())
    writer.replace([_page("general coating use", 1)])
    writer.close()
    validator = PageIndex(database, embedder=KeywordEmbedder())
    assert validator.pages()
    assert validator.query("coating", limit=1)
    validator.close()

    database.rename(tmp_path / "chroma.validated")

    assert (tmp_path / "chroma.validated").is_dir()


def test_closing_one_index_does_not_stop_another_client(tmp_path: Path) -> None:
    first = PageIndex(tmp_path / "first", embedder=KeywordEmbedder())
    second = PageIndex(tmp_path / "second", embedder=KeywordEmbedder())
    first.replace([_page("first coating evidence", 1)])
    second.replace([_page("second coating evidence", 1)])

    first.close()

    assert second.pages()[0].text == "second coating evidence"
    second.close()


def test_index_persists_and_checks_catalog_fingerprint(tmp_path: Path) -> None:
    database = tmp_path / "chroma"
    with PageIndex(database, embedder=KeywordEmbedder()) as index:
        index.replace([_page("approved evidence", 1)], catalog_fingerprint="abc123")

    with PageIndex(database, embedder=KeywordEmbedder()) as reopened:
        assert reopened.catalog_fingerprint == "abc123"
        reopened.assert_catalog_fingerprint("abc123")
        with pytest.raises(ValueError, match="catalog fingerprint"):
            reopened.assert_catalog_fingerprint("different")
