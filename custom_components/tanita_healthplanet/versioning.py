"""Stable semantic-version normalization for installation checks."""

from __future__ import annotations

from awesomeversion import (
    AwesomeVersion,
    AwesomeVersionException,
    AwesomeVersionStrategy,
)


def normalize_version(value: str | None) -> str | None:
    """Return a canonical semantic version while accepting a conventional v prefix."""
    if not isinstance(value, str) or not (candidate := value.strip()):
        return None
    try:
        parsed = AwesomeVersion(
            candidate,
            ensure_strategy=[AwesomeVersionStrategy.SEMVER],
        )
    except AwesomeVersionException:
        return None
    return parsed.string


def versions_equal(left: str | None, right: str | None) -> bool:
    """Compare two versions only after successful semantic normalization."""
    normalized_left = normalize_version(left)
    normalized_right = normalize_version(right)
    return (
        normalized_left is not None
        and normalized_right is not None
        and normalized_left == normalized_right
    )


def version_is_newer(candidate: str | None, baseline: str | None) -> bool:
    """Return whether a valid semantic candidate is newer than a valid baseline."""
    normalized_candidate = normalize_version(candidate)
    normalized_baseline = normalize_version(baseline)
    if normalized_candidate is None or normalized_baseline is None:
        return False
    return AwesomeVersion(normalized_candidate) > AwesomeVersion(normalized_baseline)
