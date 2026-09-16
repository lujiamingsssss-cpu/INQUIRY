"""本机配置读取的回归测试。

重点钉住两件事：

1. **有无 UTF-8 BOM 都能正确读取**——这正是让启动脚本解析配置文件时踩过的坑：
   编辑器加了 BOM，首行键名被读错，表现为"密钥配了却读不到"，且不报错。
2. **已存在的环境变量优先**——本机文件不得覆盖调用方显式设置的值。
"""

from pathlib import Path

from chemical_trade_copilot.local_settings import (
    env_file_path,
    load_local_settings,
    parse_env_file,
    repo_root,
)


def test_env_file_path_defaults_to_repo_local_file(monkeypatch) -> None:
    monkeypatch.delenv("CHEMICAL_TRADE_ENV_FILE", raising=False)

    assert env_file_path() == repo_root() / ".env.local"


def test_env_file_path_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("CHEMICAL_TRADE_ENV_FILE", "D:/somewhere/other.env")

    assert env_file_path() == Path("D:/somewhere/other.env")


def test_repo_root_contains_the_project_manifest() -> None:
    root = repo_root()

    assert (root / "pyproject.toml").is_file()
    assert (root / "src" / "chemical_trade_copilot").is_dir()


def test_parse_env_file_reads_plain_key_values(tmp_path: Path) -> None:
    path = tmp_path / ".env.local"
    path.write_text(
        "DEEPSEEK_API_KEY=sk-test\nCHEMICAL_TRADE_MATERIALS_ROOT=G:\\materials\n",
        encoding="utf-8",
    )

    assert parse_env_file(path) == {
        "DEEPSEEK_API_KEY": "sk-test",
        "CHEMICAL_TRADE_MATERIALS_ROOT": "G:\\materials",
    }


def test_parse_env_file_tolerates_a_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / ".env.local"
    path.write_text("DEEPSEEK_API_KEY=sk-bom\n", encoding="utf-8-sig")

    values = parse_env_file(path)

    assert values["DEEPSEEK_API_KEY"] == "sk-bom"
    assert "\ufeffDEEPSEEK_API_KEY" not in values


def test_parse_env_file_skips_blanks_comments_and_junk(tmp_path: Path) -> None:
    path = tmp_path / ".env.local"
    path.write_text(
        "# comment\n\nNOT_A_PAIR\nKEY_WITH_SPACES = value \n",
        encoding="utf-8",
    )

    assert parse_env_file(path) == {"KEY_WITH_SPACES": "value"}


def test_parse_env_file_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert parse_env_file(tmp_path / "absent.env") == {}


def test_load_local_settings_does_not_override_existing_environment(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / ".env.local"
    path.write_text(
        "DEEPSEEK_API_KEY=from-file\nONLY_IN_FILE=present\n", encoding="utf-8"
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-process")
    monkeypatch.delenv("ONLY_IN_FILE", raising=False)

    values = load_local_settings(path)

    assert values == {"DEEPSEEK_API_KEY": "from-file", "ONLY_IN_FILE": "present"}
    import os

    assert os.environ["DEEPSEEK_API_KEY"] == "from-process"
    assert os.environ["ONLY_IN_FILE"] == "present"
