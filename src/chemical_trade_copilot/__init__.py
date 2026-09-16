"""Chemical Trade AI Copilot retrieval foundation."""

import os

__version__ = "0.1.0"


def sanitize_no_proxy(value: str) -> str:
    """剔除 ``no_proxy`` 中的 IPv6 条目，只保留主机名与 IPv4。

    背景：``httpx`` 构造客户端时会把 ``no_proxy`` 的每个条目当作 URL 模式解析
    （``URLPattern("all://" + entry)``）。``[::1]`` 这类方括号 IPv6 字面量会触发
    ``InvalidURL: Invalid port: ':1]'``，导致**建立客户端这一步就失败**——现象是
    本地向量模型加载与模型 API 调用整体不可用。

    方括号 IPv6 是 ``no_proxy`` 的合法写法，企业代理环境下并不罕见，因此不能要求
    使用者去改系统环境变量。这里做最小剔除：保留主机名与 IPv4 条目及其顺序，
    只丢弃含 ``[`` 或 ``:`` 的条目（IPv6 字面量）。代价是 IPv6 目标改走代理，
    对本工具实际访问的端点没有影响。
    """
    kept = [
        entry.strip()
        for entry in value.split(",")
        if entry.strip() and "[" not in entry and ":" not in entry
    ]
    return ",".join(kept)


def _apply_environment_compatibility() -> None:
    """在包被导入时修正会直接破坏 httpx 的代理环境写法。"""
    for name in ("NO_PROXY", "no_proxy"):
        current = os.environ.get(name)
        if not current:
            continue
        cleaned = sanitize_no_proxy(current)
        if cleaned != current:
            os.environ[name] = cleaned


_apply_environment_compatibility()
