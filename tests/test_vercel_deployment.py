import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]


def test_vercel_dockerfile_runs_streamlit_on_the_platform_port() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile.vercel").read_text(encoding="utf-8")

    assert dockerfile.startswith("FROM python:3.12-slim")
    assert "pip install --no-cache-dir ." in dockerfile
    assert "CHEMICAL_TRADE_MATERIALS_ROOT=/app/deploy/materials" in dockerfile
    assert "CHEMICAL_TRADE_MATERIAL_CATALOG=/app/materials_catalog.json" in dockerfile
    assert "mktemp -d /tmp/chemical-trade-chroma.XXXXXX" in dockerfile
    assert "cp -a /app/deploy/chroma" in dockerfile
    assert "$runtime_dir/chroma" in dockerfile
    assert "export CHEMICAL_TRADE_DATABASE=" in dockerfile
    assert "python -m streamlit run" in dockerfile
    assert "src/chemical_trade_copilot/streamlit_app.py" in dockerfile
    assert "--server.address=0.0.0.0" in dockerfile
    assert "--server.port=${PORT:-80}" in dockerfile


def test_container_context_excludes_local_and_task_only_state() -> None:
    ignored = set(
        line.strip()
        for line in (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )

    assert {
        ".git",
        ".venv",
        ".worktrees",
        ".playwright-cli",
        ".pytest_cache",
        "CURRENT_WORK.md",
        "tests",
        "output",
        "tmp",
    } <= ignored


def test_deployment_materials_match_the_approved_catalog() -> None:
    catalog = json.loads(
        (PROJECT_ROOT / "materials_catalog.json").read_text(encoding="utf-8")
    )
    bundled_root = PROJECT_ROOT / "deploy" / "materials"

    enabled_paths = {
        Path(entry["relative_path"])
        for entry in catalog
        if entry["enabled"]
    }
    bundled_paths = {
        path.relative_to(bundled_root)
        for path in bundled_root.rglob("*.pdf")
    }

    assert bundled_paths == enabled_paths
    for entry in catalog:
        if not entry["enabled"]:
            continue
        import hashlib

        payload = (bundled_root / entry["relative_path"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"]


def test_deployment_index_is_the_managed_catalog_generation() -> None:
    bundled_index = PROJECT_ROOT / "deploy" / "chroma"

    assert (bundled_index / ".chemical-trade-index").read_text(
        encoding="utf-8"
    ).strip() == "managed"
    assert (bundled_index / "chroma.sqlite3").stat().st_size > 0
    assert any(path.name == "data_level0.bin" for path in bundled_index.rglob("*"))
