import gc
import shutil
import time
from collections.abc import Callable
from pathlib import Path


DirectoryAction = Callable[[Path], None]
_MANAGED_MARKER = ".chemical-trade-index"


def rebuild_index(
    active: Path,
    *,
    build: DirectoryAction,
    validate: DirectoryAction,
) -> None:
    """Build and validate beside the active index before switching directories."""
    active = active.resolve()
    _validate_target(active)
    staging = active.with_name(f"{active.name}.staging")
    backup = active.with_name(f"{active.name}.backup")
    rollback = active.with_name(f"{active.name}.rollback")
    recovery = active.with_name(f"{active.name}.recovery")
    _adopt_legacy_index(active)
    _adopt_legacy_index(backup)
    _require_managed_if_present(active)
    if rollback.exists() or recovery.exists() or (
        not active.exists() and backup.exists()
    ):
        raise ValueError("Index recovery is required before rebuilding")
    _remove_exact_directory(staging)
    staging.mkdir(parents=True)
    (staging / _MANAGED_MARKER).write_text("managed\n", encoding="utf-8")
    try:
        build(staging)
        validate(staging)
    except Exception:
        _remove_exact_directory(staging)
        raise

    _remove_exact_directory(backup)
    if active.exists():
        _rename_with_transient_retry(active, backup)
    try:
        _rename_with_transient_retry(staging, active)
    except Exception:
        if backup.exists() and not active.exists():
            _rename_with_transient_retry(backup, active)
        raise


def rollback_index(active: Path) -> None:
    """Swap the active index with its one retained backup."""
    active = active.resolve()
    _validate_target(active)
    backup = active.with_name(f"{active.name}.backup")
    temporary = active.with_name(f"{active.name}.rollback")
    recovery = active.with_name(f"{active.name}.recovery")
    if not active.is_dir():
        raise FileNotFoundError(f"Active index is missing: {active}")
    _adopt_legacy_index(active)
    _adopt_legacy_index(backup)
    _require_managed_if_present(active)
    if recovery.exists() and not backup.exists():
        _require_managed_if_present(recovery)
        _rename_with_transient_retry(recovery, backup)
    elif recovery.exists():
        raise ValueError(f"Index recovery is already required: {recovery}")
    if not backup.is_dir():
        raise FileNotFoundError(f"No rollback index is available: {backup}")
    _require_managed_if_present(backup)
    _remove_exact_directory(temporary)
    _rename_with_transient_retry(active, temporary)
    try:
        _rename_with_transient_retry(backup, active)
        _rename_with_transient_retry(temporary, backup)
    except Exception:
        if temporary.exists() and not active.exists():
            _rename_with_transient_retry(temporary, active)
        elif temporary.exists() and active.exists() and not backup.exists():
            _rename_with_transient_retry(active, recovery)
            try:
                _rename_with_transient_retry(temporary, active)
            except Exception:
                if recovery.exists() and not active.exists():
                    _rename_with_transient_retry(recovery, active)
                raise
            _rename_with_transient_retry(recovery, backup)
        raise


def _validate_target(path: Path) -> None:
    if not path.name or path.parent == path:
        raise ValueError(f"Index path must name a specific directory: {path}")


def _remove_exact_directory(path: Path) -> None:
    if not path.exists():
        return
    if not path.is_dir():
        raise ValueError(f"Index lifecycle path is not a directory: {path}")
    _require_managed_if_present(path)
    shutil.rmtree(path)


def _require_managed_if_present(path: Path) -> None:
    if not path.exists():
        return
    if not path.is_dir() or not (path / _MANAGED_MARKER).is_file():
        raise ValueError(f"Refusing to modify a directory that is not a managed index: {path}")


def _adopt_legacy_index(path: Path) -> None:
    if not path.exists() or (path / _MANAGED_MARKER).is_file():
        return
    project_file = path.parent / "pyproject.toml"
    allowed_name = path.name in {".chroma", ".chroma.backup"}
    is_this_project = project_file.is_file() and (
        'name = "chemical-trade-copilot"'
        in project_file.read_text(encoding="utf-8")
    )
    if allowed_name and is_this_project and (path / "chroma.sqlite3").is_file():
        (path / _MANAGED_MARKER).write_text("managed legacy index\n", encoding="utf-8")


def _rename_with_transient_retry(source: Path, target: Path) -> None:
    deadline = time.monotonic() + 2.0
    while True:
        try:
            source.rename(target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            gc.collect()
            time.sleep(0.05)
