from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README_PATHS = (ROOT / "README.md", ROOT / "README.zh-TW.md")
HACS_URL = (
    "https://my.home-assistant.io/redirect/hacs_repository/"
    "?owner=weihaochiu&repository=home-assistant-TANITA-healthplanet&category=integration"
)
CONFIG_FLOW_URL = (
    "https://my.home-assistant.io/redirect/config_flow_start/?domain=tanita_healthplanet"
)
HACS_BADGE = "https://my.home-assistant.io/badges/hacs_repository.svg"
CONFIG_FLOW_BADGE = "https://my.home-assistant.io/badges/config_flow_start.svg"


def test_readmes_contain_canonical_install_links_and_badges():
    for readme_path in README_PATHS:
        readme = readme_path.read_text(encoding="utf-8")
        assert HACS_URL in readme
        assert CONFIG_FLOW_URL in readme
        assert HACS_BADGE in readme
        assert CONFIG_FLOW_BADGE in readme
