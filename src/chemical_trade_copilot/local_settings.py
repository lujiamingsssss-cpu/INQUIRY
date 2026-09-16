"""本机配置读取（只读，不写入）。

机器相关信息（模型密钥、资料根目录）不进入版本控制，放在仓库根目录的
``.env.local``。让**应用自己读取**它，而不是让启动脚本用批处理解析，原因：

- 批处理的 ``for /f`` 受控制台代码页影响，含中文的路径容易被误解码；
- 编辑器若给文件加上 UTF-8 BOM，批处理会把首行键名读错，表现为"密钥明明配了却读不到"，
  而且不报错。

Python 侧用 ``utf-8-sig`` 解码，天然兼容有无 BOM 两种情况；已存在的环境变量优先，
不会被文件覆盖。本模块**只读取，不写入任何文件**。
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["env_file_path", "load_local_settings", "parse_env_file", "repo_root"]


def repo_root() -> Path:
    """仓库根目录：``<root>/src/chemical_trade_copilot/local_settings.py``。"""
    return Path(__file__).resolve().parents[2]


def env_file_path() -> Path:
    """本机配置文件路径；可用 ``CHEMICAL_TRADE_ENV_FILE`` 覆盖（部署与测试用）。"""
    override = os.environ.get("CHEMICAL_TRADE_ENV_FILE")
    return Path(override) if override else (repo_root() / ".env.local")


def parse_env_file(path: Path) -> dict[str, str]:
    """解析 ``KEY=VALUE`` 形式的配置文件；忽略空行与 ``#`` 注释。"""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            values[key] = value.strip()
    return values


def load_local_settings(path: Path | None = None) -> dict[str, str]:
    """把 ``.env.local`` 中尚未存在的变量写入进程环境，返回读取到的全部键值。"""
    values = parse_env_file(path or env_file_path())
    for key, value in values.items():
        if key and not os.environ.get(key):
            os.environ[key] = value
    return values
