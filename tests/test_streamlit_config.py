import tomllib
from pathlib import Path


CONFIG = Path(__file__).parents[1] / ".streamlit" / "config.toml"


def test_streamlit_theme_matches_mineral_ink_style_contract() -> None:
    with CONFIG.open("rb") as stream:
        config = tomllib.load(stream)

    assert config["client"]["toolbarMode"] == "minimal"
    assert config["server"]["fileWatcherType"] == "none"
    assert config["theme"]["primaryColor"] == "#316A5D"
    assert config["theme"]["backgroundColor"] == "#F2EFE7"
    assert config["theme"]["secondaryBackgroundColor"] == "#FBFAF6"
    assert config["theme"]["textColor"] == "#102B27"
