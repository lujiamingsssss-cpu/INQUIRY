"""代理环境兼容性回归测试。

根因（真实复现过）：``no_proxy`` 里的方括号 IPv6 字面量会让 httpx 在构造客户端时抛
``InvalidURL: Invalid port: ':1]'``，导致本地向量模型加载与模型 API 调用**整体失败**。
表现为：命令行重建索引崩溃、新写的双击启动脚本一启动就报错。

方括号 IPv6 是 ``no_proxy`` 的合法写法，企业代理环境下并不罕见，因此由本包在导入时
做最小清洗，而不是要求使用者修改系统环境变量。

这里钉住的是**本项目自己的契约**：清洗规则、清洗幂等、以及清洗后 httpx 确实可用。
不钉 httpx 内部在合成环境下的具体报错行为——那依赖代理变量的组合，不适合作为回归断言。
"""

import os

import httpx

from chemical_trade_copilot import _apply_environment_compatibility, sanitize_no_proxy


def test_sanitize_drops_ipv6_entries_and_keeps_the_rest() -> None:
    assert sanitize_no_proxy("localhost,127.0.0.1,::1,[::1]") == "localhost,127.0.0.1"
    assert sanitize_no_proxy("[::1]") == ""
    assert sanitize_no_proxy("") == ""
    assert sanitize_no_proxy("example.com, 10.0.0.1 ") == "example.com,10.0.0.1"
    assert sanitize_no_proxy("localhost") == "localhost"


def test_sanitize_leaves_nothing_httpx_cannot_parse() -> None:
    cleaned = sanitize_no_proxy("localhost,127.0.0.1,::1,[::1],example.com")

    assert "[" not in cleaned
    assert "]" not in cleaned
    assert ":" not in cleaned
    assert cleaned == "localhost,127.0.0.1,example.com"


def test_sanitize_is_idempotent() -> None:
    once = sanitize_no_proxy("localhost,[::1],10.0.0.1")
    assert sanitize_no_proxy(once) == once


def test_compatibility_pass_cleans_a_bracketed_no_proxy(monkeypatch) -> None:
    """导入时执行的这一步必须把两种大小写都清干净。"""
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,::1,[::1]")
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1,::1,[::1]")

    _apply_environment_compatibility()

    assert os.environ["NO_PROXY"] == "localhost,127.0.0.1"
    assert os.environ["no_proxy"] == "localhost,127.0.0.1"


def test_cleaned_environment_builds_a_usable_httpx_client(monkeypatch) -> None:
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,::1,[::1]")
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1,::1,[::1]")

    _apply_environment_compatibility()
    client = httpx.Client(trust_env=True)
    client.close()


def test_compatibility_pass_ignores_absent_values(monkeypatch) -> None:
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)

    _apply_environment_compatibility()

    assert "NO_PROXY" not in os.environ
    assert "no_proxy" not in os.environ
