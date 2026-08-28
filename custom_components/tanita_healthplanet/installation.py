"""Read-only installed-file version verification."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import ClientError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, HACS_REPOSITORY_FULL_NAME, USER_AGENT, VERSION
from .versioning import normalize_version, version_is_newer, versions_equal

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, State

ERROR_MANIFEST_MISSING = "installation_manifest_missing"
ERROR_MANIFEST_INVALID = "installation_manifest_invalid"
GITHUB_LATEST_RELEASE_URL = (
    f"https://api.github.com/repos/{HACS_REPOSITORY_FULL_NAME}/releases/latest"
)
GITHUB_CHECK_TIMEOUT_SECONDS = 10

STATUS_NORMAL = "normal"
STATUS_UPDATE_AVAILABLE = "update_available"
STATUS_HACS_METADATA_STALE = "hacs_metadata_stale"
STATUS_INSTALLATION_DRIFT = "installation_drift"
STATUS_INSTALLATION_INVALID = "installation_invalid"
STATUS_UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DiskManifestVersion:
    """Privacy-safe result of reading the integration manifest."""

    version: str | None
    error_id: str | None = None


@dataclass(frozen=True, slots=True)
class InstallationVersions:
    """The four version identities relevant to Safe Update."""

    runtime: str
    disk: str | None
    hacs_installed: str | None
    hacs_latest: str | None
    disk_error_id: str | None = None
    github_latest: str | None = None
    github_check_complete: bool = False

    @property
    def consistent(self) -> bool:
        return self.disk_error_id is None and versions_equal(self.disk, self.hacs_installed)

    @property
    def update_metadata_status(self) -> str:
        """Classify installation and update metadata without choosing an install target."""
        if self.disk_error_id is not None or normalize_version(self.disk) is None:
            return STATUS_INSTALLATION_INVALID
        if normalize_version(self.hacs_installed) is None:
            return STATUS_UNKNOWN
        if not versions_equal(self.disk, self.hacs_installed):
            return STATUS_INSTALLATION_DRIFT
        if normalize_version(self.hacs_latest) is None:
            return STATUS_UNKNOWN
        if self.github_latest is not None and version_is_newer(
            self.github_latest, self.hacs_latest
        ):
            return STATUS_HACS_METADATA_STALE
        if version_is_newer(self.hacs_latest, self.hacs_installed):
            return STATUS_UPDATE_AVAILABLE
        if not self.github_check_complete:
            return STATUS_UNKNOWN
        return STATUS_NORMAL


async def async_get_github_latest_version(hass: HomeAssistant) -> str | None:
    """Fetch the public latest stable release as a supplementary freshness signal."""
    try:
        async with asyncio.timeout(GITHUB_CHECK_TIMEOUT_SECONDS):
            response = await async_get_clientsession(hass).get(
                GITHUB_LATEST_RELEASE_URL,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": USER_AGENT,
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            try:
                if response.status != 200:
                    return None
                payload = await response.json(content_type=None)
            finally:
                response.release()
    except (TimeoutError, ClientError, ValueError, TypeError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("draft") is True
        or payload.get("prerelease") is True
    ):
        return None
    tag_name = payload.get("tag_name")
    return tag_name if isinstance(tag_name, str) and normalize_version(tag_name) else None


class ActualInstalledVersionVerifier:
    """Verify only the public HA config-path integration manifest."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    @property
    def manifest_path(self) -> Path:
        return Path(self.hass.config.path("custom_components", DOMAIN, "manifest.json"))

    @staticmethod
    def _read_manifest(path: Path) -> DiskManifestVersion:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return DiskManifestVersion(None, ERROR_MANIFEST_MISSING)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return DiskManifestVersion(None, ERROR_MANIFEST_INVALID)
        if not isinstance(payload, dict) or payload.get("domain") != DOMAIN:
            return DiskManifestVersion(None, ERROR_MANIFEST_INVALID)
        if not isinstance(version := payload.get("version"), str) or not version:
            return DiskManifestVersion(None, ERROR_MANIFEST_INVALID)
        if normalize_version(version) is None:
            return DiskManifestVersion(version, ERROR_MANIFEST_INVALID)
        return DiskManifestVersion(version)

    async def async_read(self) -> DiskManifestVersion:
        """Read without blocking HA's event loop."""
        return await self.hass.async_add_executor_job(self._read_manifest, self.manifest_path)

    async def async_snapshot(self, state: State | None) -> InstallationVersions:
        """Capture runtime, disk, and public HACS entity versions."""
        disk = await self.async_read()
        installed = state.attributes.get("installed_version") if state else None
        latest = state.attributes.get("latest_version") if state else None
        return InstallationVersions(
            runtime=VERSION,
            disk=disk.version,
            hacs_installed=installed if isinstance(installed, str) else None,
            hacs_latest=latest if isinstance(latest, str) else None,
            disk_error_id=disk.error_id,
        )
