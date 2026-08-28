from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.validate_release import ReleaseValidationError, validate_release_metadata

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def test_release_workflow_has_secure_gated_release_contract():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert '      - "v*.*.*"' in source
    assert "workflow_dispatch:" in source
    assert "contents: write" in source
    assert "github.token" in source
    assert "scripts/validate_release.py" in source
    assert "--require-annotated-tag" in source
    assert "--require-main-head" in source
    assert "needs: [validate_release, test, hacs, hassfest]" in source
    assert 'gh release view "$TAG"' in source
    assert 'gh release create "$TAG"' in source
    assert "--verify-tag" in source
    assert "scripts/build_release.py" in source
    assert "release-notes.md" in source
    assert "healthplanet_for_home_assistant.zip" in source
    assert "SHA256SUMS.txt" in source
    assert "--generate-notes" not in source
    assert "pull_request_target" not in source
    assert "packages: write" not in source
    assert "actions: write" not in source
    assert "id-token: write" not in source


def test_release_metadata_matches_v023():
    manifest = json.loads(
        (ROOT / "custom_components" / "tanita_healthplanet" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["version"] == "0.2.3"
    assert validate_release_metadata(ROOT, "v0.2.3") == "0.2.3"


@pytest.mark.parametrize(
    "tag",
    ("vtest", "release", "foo", "v0.2", "v0.2.1-beta-random"),
)
def test_release_metadata_rejects_non_stable_tags(tag: str):
    with pytest.raises(ReleaseValidationError, match="release_tag_not_stable_semver"):
        validate_release_metadata(ROOT, tag)
