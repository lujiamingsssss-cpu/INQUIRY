"""已核验结论的本机缓存：同一条询盘给出同一个结论。

这是**内部一致性规则，不是面向使用者的"数据存储"功能**——界面不提供历史浏览、检索或导出，
也没有账号与记录页。它解决的问题是：模型的文字表达天然每次不同，偶发的措辞越界会被本地
证据门禁拒绝并降级，于是同一条询盘"这次答不出、下次又能答出"，对业务判断是噪音。

规则：

- **只缓存通过门禁的结论**。被拒（降级）的结果一律不写缓存，下次仍真实重算，
  避免把偶发失败固化成"这条询盘永远答不出"。
- **命中时不调用任何模型**：用缓存里的检索计划在本地重跑一次检索，核对证据身份与资料清单
  指纹；只要有一处不一致就当作未命中，走正常流程。
- 失效条件：资料清单指纹、模型名、本模块的结构版本任一变化。
- 内容只有：询盘文本、检索计划、证据身份（产品 / 文件 / 物理页）与已核验结论。
  **密钥与凭据永不进入缓存。**
- 使用者可随时删除缓存文件清空，路径见 ``cache_path()``。
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from .local_settings import repo_root

__all__ = [
    "CACHE_SCHEMA_VERSION",
    "CacheEntry",
    "cache_key",
    "cache_path",
    "clear_cache",
    "load_entries",
    "lookup",
    "normalize_inquiry",
    "store",
]

# 结构或语义发生不兼容变化时递增，使旧缓存自动失效。
CACHE_SCHEMA_VERSION = 1

MAX_ENTRIES = 500


@dataclass(frozen=True, slots=True)
class CacheEntry:
    key: str
    inquiry: str
    model: str
    search_query: str
    document_types: tuple[str, ...]
    evidence: tuple[tuple[str, str, int], ...]
    analysis_json: str
    created_at: str

    def to_json(self) -> dict[str, object]:
        payload = asdict(self)
        payload["document_types"] = list(self.document_types)
        payload["evidence"] = [list(item) for item in self.evidence]
        return payload

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> "CacheEntry | None":
        try:
            return cls(
                key=str(payload["key"]),
                inquiry=str(payload["inquiry"]),
                model=str(payload["model"]),
                search_query=str(payload["search_query"]),
                document_types=tuple(str(v) for v in payload["document_types"]),  # type: ignore[arg-type]
                evidence=tuple(
                    (str(item[0]), str(item[1]), int(item[2]))
                    for item in payload["evidence"]  # type: ignore[union-attr]
                ),
                analysis_json=str(payload["analysis_json"]),
                created_at=str(payload["created_at"]),
            )
        except (KeyError, TypeError, ValueError, IndexError):
            return None


def cache_path(root: Path | None = None) -> Path:
    """缓存文件位置；可用 ``CHEMICAL_TRADE_CACHE_FILE`` 覆盖（部署与测试用）。"""
    override = os.environ.get("CHEMICAL_TRADE_CACHE_FILE")
    if override:
        return Path(override)
    return (root or repo_root()) / ".cache" / "verified_answers.json"


def normalize_inquiry(inquiry: str) -> str:
    """归一化询盘文本，使仅空白或大小写差异的重复询盘命中同一结论。"""
    return " ".join(inquiry.split()).casefold()


def cache_key(
    inquiry: str,
    *,
    catalog_fingerprint: str,
    model: str,
) -> str:
    payload = json.dumps(
        {
            "schema": CACHE_SCHEMA_VERSION,
            "inquiry": normalize_inquiry(inquiry),
            "catalog_fingerprint": catalog_fingerprint,
            "model": model,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def load_entries(path: Path | None = None) -> dict[str, CacheEntry]:
    """读取全部缓存条目。文件缺失或损坏时返回空表，绝不因此让主流程失败。"""
    target = path or cache_path()
    if not target.is_file():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        return {}
    entries: dict[str, CacheEntry] = {}
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        entry = CacheEntry.from_json(raw)
        if entry is not None:
            entries[entry.key] = entry
    return entries


def lookup(
    inquiry: str,
    *,
    catalog_fingerprint: str,
    model: str,
    path: Path | None = None,
) -> CacheEntry | None:
    key = cache_key(inquiry, catalog_fingerprint=catalog_fingerprint, model=model)
    return load_entries(path).get(key)


def store(entry: CacheEntry, path: Path | None = None) -> None:
    """写入一条**已通过门禁**的结论；写入失败不影响主流程。"""
    target = path or cache_path()
    entries = load_entries(target)
    entries[entry.key] = entry
    if len(entries) > MAX_ENTRIES:
        ordered = sorted(entries.values(), key=lambda item: item.created_at)
        entries = {item.key: item for item in ordered[-MAX_ENTRIES:]}
    payload = {
        "schema": CACHE_SCHEMA_VERSION,
        "entries": [item.to_json() for item in entries.values()],
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=target.parent,
            prefix=target.name + ".",
            suffix=".tmp",
            delete=False,
        )
        with handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
        Path(handle.name).replace(target)
    except OSError:
        return


def clear_cache(path: Path | None = None) -> bool:
    """删除缓存文件；用于"清空本机已核验结论"。"""
    target = path or cache_path()
    try:
        target.unlink()
        return True
    except FileNotFoundError:
        return False


def evidence_identity(
    items: Sequence[object],
) -> tuple[tuple[str, str, int], ...]:
    """把检索结果或页记录归一为证据身份，用于比对缓存与本次检索是否一致。"""
    identities = {
        (str(getattr(item, "product")), str(getattr(item, "source_file")), int(getattr(item, "page_number")))
        for item in items
    }
    return tuple(sorted(identities))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
