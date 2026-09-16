from pathlib import Path

import pytest

from chemical_trade_copilot.index_lifecycle import rebuild_index, rollback_index


def _write_version(path: Path, version: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".chemical-trade-index").write_text("managed\n", encoding="utf-8")
    (path / "version.txt").write_text(version, encoding="utf-8")


def _read_version(path: Path) -> str:
    return (path / "version.txt").read_text(encoding="utf-8")


def test_rebuild_keeps_active_index_when_staging_validation_fails(
    tmp_path: Path,
) -> None:
    active = tmp_path / "index"
    _write_version(active, "old")

    def build(staging: Path) -> None:
        _write_version(staging, "invalid")

    def reject(staging: Path) -> None:
        raise ValueError(f"Rejected {_read_version(staging)}")

    with pytest.raises(ValueError, match="Rejected invalid"):
        rebuild_index(active, build=build, validate=reject)

    assert _read_version(active) == "old"
    assert not (tmp_path / "index.staging").exists()
    assert not (tmp_path / "index.backup").exists()


def test_rebuild_switches_valid_staging_and_keeps_one_backup(tmp_path: Path) -> None:
    active = tmp_path / "index"
    _write_version(active, "old")

    rebuild_index(
        active,
        build=lambda staging: _write_version(staging, "new"),
        validate=lambda staging: None,
    )

    assert _read_version(active) == "new"
    assert _read_version(tmp_path / "index.backup") == "old"
    assert not (tmp_path / "index.staging").exists()


def test_rebuild_retries_a_transient_windows_rename_denial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active = tmp_path / "index"
    _write_version(active, "old")
    original_rename = Path.rename
    attempts = 0

    def transient_rename(source: Path, target: Path):
        nonlocal attempts
        if source.name == "index.staging" and target == active.resolve():
            attempts += 1
            if attempts == 1:
                raise PermissionError(5, "transient file lock", str(source))
        return original_rename(source, target)

    monkeypatch.setattr(Path, "rename", transient_rename)

    rebuild_index(
        active,
        build=lambda staging: _write_version(staging, "new"),
        validate=lambda staging: None,
    )

    assert attempts == 2
    assert _read_version(active) == "new"


def test_rollback_swaps_active_and_backup_versions(tmp_path: Path) -> None:
    active = tmp_path / "index"
    backup = tmp_path / "index.backup"
    _write_version(active, "new")
    _write_version(backup, "old")

    rollback_index(active)

    assert _read_version(active) == "old"
    assert _read_version(backup) == "new"


def test_rollback_requires_a_backup(tmp_path: Path) -> None:
    _write_version(tmp_path / "index", "active")
    with pytest.raises(FileNotFoundError, match="No rollback index"):
        rollback_index(tmp_path / "index")


def test_rebuild_refuses_to_move_or_delete_an_unmanaged_directory(
    tmp_path: Path,
) -> None:
    active = tmp_path / "index"
    active.mkdir()
    important = active / "user-data.txt"
    important.write_text("preserve", encoding="utf-8")

    with pytest.raises(ValueError, match="managed index"):
        rebuild_index(
            active,
            build=lambda staging: _write_version(staging, "new"),
            validate=lambda staging: None,
        )

    assert important.read_text(encoding="utf-8") == "preserve"


def test_rollback_restores_original_active_when_final_backup_rename_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active = tmp_path / "index"
    backup = tmp_path / "index.backup"
    _write_version(active, "new")
    _write_version(backup, "old")
    original_rename = Path.rename

    def fail_final_rename(source: Path, target: Path):
        if source.name == "index.rollback" and target.name == "index.backup":
            raise RuntimeError("injected final rename failure")
        return original_rename(source, target)

    monkeypatch.setattr(Path, "rename", fail_final_rename)

    with pytest.raises(RuntimeError, match="injected final rename failure"):
        rollback_index(active)

    assert _read_version(active) == "new"
    assert _read_version(backup) == "old"
    assert not (tmp_path / "index.recovery").exists()


def test_rebuild_refuses_crash_state_instead_of_deleting_only_backup(
    tmp_path: Path,
) -> None:
    active = tmp_path / "index"
    backup = tmp_path / "index.backup"
    staging = tmp_path / "index.staging"
    _write_version(backup, "old")
    _write_version(staging, "new")

    with pytest.raises(ValueError, match="recovery is required"):
        rebuild_index(
            active,
            build=lambda path: _write_version(path, "replacement"),
            validate=lambda path: None,
        )

    assert _read_version(backup) == "old"
    assert _read_version(staging) == "new"


def test_rollback_recovers_stranded_backup_before_retrying(tmp_path: Path) -> None:
    active = tmp_path / "index"
    recovery = tmp_path / "index.recovery"
    _write_version(active, "new")
    _write_version(recovery, "old")

    rollback_index(active)

    assert _read_version(active) == "old"
    assert _read_version(tmp_path / "index.backup") == "new"
    assert not recovery.exists()
