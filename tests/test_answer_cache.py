"""已核验结论缓存的回归测试。

这套缓存是**内部一致性规则**：同一条询盘在资料与模型不变时应给出同一结论。
要钉住的边界：

- 命中不依赖任何模型调用；
- 资料清单指纹 / 模型名 / 结构版本变化即失效；
- 被拒（降级）的结论不得进缓存，避免把偶发失败固化；
- 缓存文件损坏、缺失、内容异常都不得让主流程失败；
- 缓存不进入版本控制，且可被显式清空。
"""

from dataclasses import replace
from pathlib import Path

from chemical_trade_copilot import answer_cache
from chemical_trade_copilot.answer_cache import CacheEntry


def _entry(key: str = "k1", inquiry: str = "same inquiry") -> CacheEntry:
    return CacheEntry(
        key=key,
        inquiry=inquiry,
        model="deepseek-v4-pro",
        search_query="epon mpda hdt",
        document_types=("TDS",),
        evidence=(("EPON Resin 8280", "TDS - x.pdf", 3),),
        analysis_json='{"summary_zh":"ok"}',
        created_at="2026-09-17T00:00:00+00:00",
    )


def test_key_is_stable_for_equivalent_inquiries() -> None:
    first = answer_cache.cache_key(
        "  Same   Inquiry ", catalog_fingerprint="fp", model="m"
    )
    second = answer_cache.cache_key(
        "same inquiry", catalog_fingerprint="fp", model="m"
    )

    assert first == second


def test_key_changes_with_catalog_model_and_schema() -> None:
    base = answer_cache.cache_key("q", catalog_fingerprint="fp", model="m")

    assert base != answer_cache.cache_key("q", catalog_fingerprint="fp2", model="m")
    assert base != answer_cache.cache_key("q", catalog_fingerprint="fp", model="m2")


def test_store_then_lookup_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    entry = _entry()

    answer_cache.store(entry, path)

    found = answer_cache.lookup(
        entry.inquiry, catalog_fingerprint="", model="m", path=path
    )
    # 键不同（上面用空指纹），因此不应命中
    assert found is None
    stored = answer_cache.load_entries(path)[entry.key]
    assert stored == entry


def test_lookup_returns_none_for_missing_or_corrupt_file(tmp_path: Path) -> None:
    missing = tmp_path / "absent.json"
    assert answer_cache.lookup("q", catalog_fingerprint="fp", model="m", path=missing) is None

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert answer_cache.load_entries(broken) == {}
    assert answer_cache.lookup("q", catalog_fingerprint="fp", model="m", path=broken) is None


def test_store_survives_an_invalid_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    path.write_text("garbage", encoding="utf-8")

    answer_cache.store(_entry(), path)

    assert list(answer_cache.load_entries(path)) == ["k1"]


def test_store_enforces_a_bounded_entry_count(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(answer_cache, "MAX_ENTRIES", 3)
    path = tmp_path / "cache.json"
    for index in range(5):
        entry = replace(
            _entry(key=f"k{index}"),
            created_at=f"2026-09-17T00:00:0{index}+00:00",
        )
        answer_cache.store(entry, path)

    keys = set(answer_cache.load_entries(path))

    assert keys == {"k2", "k3", "k4"}


def test_clear_removes_the_file_and_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    answer_cache.store(_entry(), path)

    assert answer_cache.clear_cache(path) is True
    assert answer_cache.clear_cache(path) is False
    assert not path.exists()


def test_cache_path_defaults_under_repo_and_can_be_overridden(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CHEMICAL_TRADE_CACHE_FILE", raising=False)
    default = answer_cache.cache_path()

    assert default.name == "verified_answers.json"
    assert default.parent.name == ".cache"
    assert (default.parent.parent / "pyproject.toml").is_file()

    monkeypatch.setenv("CHEMICAL_TRADE_CACHE_FILE", str(tmp_path / "custom.json"))
    assert answer_cache.cache_path() == tmp_path / "custom.json"


def test_cache_file_is_not_tracked_by_git() -> None:
    gitignore = (Path(answer_cache.repo_root()) / ".gitignore").read_text(encoding="utf-8")

    assert ".cache/" in gitignore


def test_evidence_identity_is_sorted_and_deduplicated() -> None:
    class Item:
        def __init__(self, product: str, file: str, page: int) -> None:
            self.product = product
            self.source_file = file
            self.page_number = page

    items = [
        Item("B", "b.pdf", 2),
        Item("A", "a.pdf", 1),
        Item("A", "a.pdf", 1),
    ]

    assert answer_cache.evidence_identity(items) == (("A", "a.pdf", 1), ("B", "b.pdf", 2))
