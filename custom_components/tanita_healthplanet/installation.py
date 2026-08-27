"""Read-only installed-file version verification."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .const import DOMAIN, VERSION

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, State

ERROR_MANIFEST_MISSING = "installation_manifest_missing"
ERROR_MANIFEST_INVALID = "installation_manifest_invalid"


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

    @property
    def consistent(self) -> bool:
        return (
            self.disk_error_id is None
            and self.disk is not None
            and self.hacs_installed is not None
            and self.disk == self.hacs_installed
        )


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
