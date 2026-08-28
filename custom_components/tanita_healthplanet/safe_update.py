"""Native, user-initiated backup-first HACS update orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from .const import (
    CONF_HACS_UPDATE_UNIQUE_ID,
    CONF_RESTART_AFTER_SAFE_UPDATE,
    DEFAULT_RESTART_AFTER_SAFE_UPDATE,
    DOMAIN,
    HACS_REPOSITORY_DISPLAY_NAME,
    HACS_REPOSITORY_FULL_NAME,
    HACS_REPOSITORY_OWNER,
    SAFE_UPDATE_BACKUP_COMPLETION_TIMEOUT_SECONDS,
    SAFE_UPDATE_BACKUP_START_TIMEOUT_SECONDS,
    SAFE_UPDATE_INSTALL_TIMEOUT_SECONDS,
    SAFE_UPDATE_RESTART_DELAY_SECONDS,
    VERSION,
)
from .installation import (
    STATUS_HACS_METADATA_STALE,
    STATUS_UNKNOWN,
    ActualInstalledVersionVerifier,
    DiskManifestVersion,
    InstallationVersions,
    async_get_github_latest_version,
)
from .versioning import versions_equal

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import Context, HomeAssistant, State

DATA_SAFE_UPDATE_MANAGER = "safe_update_manager"
BACKUP_EVENT_UNIQUE_ID = "automatic_backup_event"
NOTIFICATION_ID = "healthplanet_safe_update"

RESULT_SUCCESS = "success"
RESULT_NO_UPDATE = "no_update"
RESULT_BACKUP_FAILED = "backup_failed"
RESULT_BACKUP_TIMEOUT = "backup_timeout"
RESULT_UPDATE_FAILED = "update_failed"
RESULT_UPDATE_TIMEOUT = "update_timeout"
RESULT_UNSUPPORTED = "unsupported"
RESULT_BUSY = "busy"
RESULT_RESTART_FAILED = "restart_failed"
RESULT_INSTALLATION_DRIFT = "installation_drift"
RESULT_INSTALLATION_INVALID = "installation_invalid"
RESULT_HACS_METADATA_STALE = "hacs_metadata_stale"

STAGE_IDLE = "idle"
STAGE_RESOLVING = "resolving"
STAGE_CREATING_BACKUP = "creating_backup"
STAGE_WAITING_FOR_BACKUP = "waiting_for_backup"
STAGE_UPDATING = "updating"
STAGE_VERIFYING_UPDATE = "verifying_update"
STAGE_RESTARTING = "restarting"
STAGE_COMPLETED = "completed"
STAGE_FAILED = "failed"


class _StateTimeoutError(Exception):
    """Raised when a public entity did not reach a required state."""


class _StateUnavailableError(Exception):
    """Raised when a required public entity becomes unavailable."""


class _BackupServiceError(Exception):
    """Raised when Home Assistant rejects or fails the backup service call."""


def entry_order(entry: ConfigEntry) -> tuple[str, str]:
    """Return stable creation order; entry_id is a deterministic tie-breaker."""
    return (str(getattr(entry, "created_at", None) or "9999"), entry.entry_id)


def management_entry_id(hass: HomeAssistant) -> str | None:
    """Return the oldest configured entry, independent of load order."""
    entries = sorted(hass.config_entries.async_entries(DOMAIN), key=entry_order)
    return entries[0].entry_id if entries else None


def is_management_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Return whether an entry deterministically owns the one global button."""
    return entry.entry_id == management_entry_id(hass)


def management_replacement_entry_id(hass: HomeAssistant, removed_entry: ConfigEntry) -> str | None:
    """Return the successor only when the removed entry owned management."""
    remaining = sorted(
        (
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.entry_id != removed_entry.entry_id
        ),
        key=entry_order,
    )
    if not remaining or entry_order(remaining[0]) < entry_order(removed_entry):
        return None
    return remaining[0].entry_id


def _configured_option(hass: HomeAssistant, key: str, default: Any = None) -> Any:
    for entry in sorted(hass.config_entries.async_entries(DOMAIN), key=entry_order):
        if key in entry.options:
            return entry.options[key]
    return default


def configured_restart_after_update(hass: HomeAssistant) -> bool:
    """Return the installation-wide restart preference."""
    return bool(
        _configured_option(
            hass,
            CONF_RESTART_AFTER_SAFE_UPDATE,
            DEFAULT_RESTART_AFTER_SAFE_UPDATE,
        )
    )


def selected_hacs_unique_id(hass: HomeAssistant) -> str | None:
    """Return the installation-wide fallback HACS registry identity."""
    value = _configured_option(hass, CONF_HACS_UPDATE_UNIQUE_ID)
    return value if isinstance(value, str) and value else None


def hacs_unique_id_for_entity(hass: HomeAssistant, entity_id: str) -> str | None:
    """Validate a selected HACS update entity and return its stable identity."""
    from homeassistant.helpers import entity_registry as er

    registry_entry = er.async_get(hass).async_get(entity_id)
    if (
        registry_entry is None
        or registry_entry.platform != "hacs"
        or not registry_entry.entity_id.startswith("update.")
    ):
        return None
    return registry_entry.unique_id


class SafeUpdateManager:
    """Coordinate one fail-closed Safe Update operation per HA installation."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        backup_start_timeout: float = SAFE_UPDATE_BACKUP_START_TIMEOUT_SECONDS,
        backup_completion_timeout: float = SAFE_UPDATE_BACKUP_COMPLETION_TIMEOUT_SECONDS,
        install_timeout: float = SAFE_UPDATE_INSTALL_TIMEOUT_SECONDS,
        restart_delay: float = SAFE_UPDATE_RESTART_DELAY_SECONDS,
        update_entity_resolver: Callable[[], str | None] | None = None,
        backup_entity_resolver: Callable[[], str | None] | None = None,
        disk_version_reader: Callable[[], Awaitable[DiskManifestVersion]] | None = None,
        github_latest_reader: Callable[[], Awaitable[str | None]] | None = None,
    ) -> None:
        self.hass = hass
        self._lock = asyncio.Lock()
        self._listeners: set[Callable[[], None]] = set()
        self._backup_start_timeout = backup_start_timeout
        self._backup_completion_timeout = backup_completion_timeout
        self._install_timeout = install_timeout
        self._restart_delay = restart_delay
        self._update_entity_resolver = update_entity_resolver
        self._backup_entity_resolver = backup_entity_resolver
        self._disk_version_reader = (
            disk_version_reader or ActualInstalledVersionVerifier(hass).async_read
        )
        self._github_latest_reader = github_latest_reader or (
            lambda: async_get_github_latest_version(hass)
        )
        self.last_result: str | None = None
        self.last_stage = STAGE_IDLE
        self.last_completed_at: datetime | None = None
        self.runtime_version = VERSION
        self.disk_version: str | None = None
        self.hacs_installed_version: str | None = None
        self.hacs_latest_version: str | None = None
        self.github_latest_version: str | None = None
        self.version_consistent = False
        self.update_metadata_status = STATUS_UNKNOWN
        self._github_check_complete = False
        self.last_error_id: str | None = None

    async def async_capture_versions(
        self, state: State | None, *, check_github: bool = False
    ) -> DiskManifestVersion:
        """Capture raw versions and optionally refresh the supplementary GitHub signal."""
        disk = await self._disk_version_reader()
        self.disk_version = disk.version
        installed = state.attributes.get("installed_version") if state else None
        latest = state.attributes.get("latest_version") if state else None
        self.hacs_installed_version = installed if isinstance(installed, str) else None
        self.hacs_latest_version = latest if isinstance(latest, str) else None
        if check_github:
            try:
                github_latest = await self._github_latest_reader()
            except Exception:
                github_latest = None
            self.github_latest_version = github_latest if isinstance(github_latest, str) else None
            self._github_check_complete = self.github_latest_version is not None
        versions = InstallationVersions(
            runtime=self.runtime_version,
            disk=disk.version,
            hacs_installed=self.hacs_installed_version,
            hacs_latest=self.hacs_latest_version,
            disk_error_id=disk.error_id,
            github_latest=self.github_latest_version,
            github_check_complete=self._github_check_complete,
        )
        self.version_consistent = versions.consistent
        self.update_metadata_status = versions.update_metadata_status
        return disk

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    def _set_stage(self, stage: str) -> None:
        self.last_stage = stage
        for listener in tuple(self._listeners):
            listener()

    def _finish(self, result: str, stage: str = STAGE_FAILED) -> str:
        self.last_result = result
        self.last_completed_at = datetime.now(UTC)
        self._set_stage(stage)
        return result

    def resolve_update_entity(self) -> str | None:
        """Resolve a renamed HACS entity without importing HACS internals."""
        if self._update_entity_resolver is not None:
            return self._update_entity_resolver()

        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er

        entities = er.async_get(self.hass)
        devices = dr.async_get(self.hass)
        automatic: list[str] = []
        fallback: list[str] = []
        configured_unique_id = selected_hacs_unique_id(self.hass)
        for registry_entry in entities.entities.values():
            if registry_entry.platform != "hacs" or not registry_entry.entity_id.startswith(
                "update."
            ):
                continue
            if configured_unique_id and registry_entry.unique_id == configured_unique_id:
                fallback.append(registry_entry.entity_id)
            state = self.hass.states.get(registry_entry.entity_id)
            release_url = state.attributes.get("release_url") if state is not None else None
            if self._release_url_matches_repository(release_url):
                automatic.append(registry_entry.entity_id)
                continue
            device = (
                devices.async_get(registry_entry.device_id) if registry_entry.device_id else None
            )
            if (
                device is not None
                and device.name == HACS_REPOSITORY_DISPLAY_NAME
                and device.manufacturer == HACS_REPOSITORY_OWNER
                and str(device.model) == "integration"
            ):
                automatic.append(registry_entry.entity_id)
        if len(automatic) == 1:
            return automatic[0]
        return fallback[0] if len(fallback) == 1 else None

    @staticmethod
    def _release_url_matches_repository(value: Any) -> bool:
        """Match the exact repository through the public update entity contract."""
        if not isinstance(value, str):
            return False
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.netloc.casefold() != "github.com":
            return False
        path = parsed.path.strip("/").casefold()
        repository = HACS_REPOSITORY_FULL_NAME.casefold()
        return path == repository or path.startswith(f"{repository}/releases/")

    def resolve_backup_entity(self) -> str | None:
        """Resolve the official automatic-backup event entity after rename."""
        if self._backup_entity_resolver is not None:
            return self._backup_entity_resolver()

        from homeassistant.helpers import entity_registry as er

        matches = [
            item.entity_id
            for item in er.async_get(self.hass).entities.values()
            if item.platform == "backup"
            and item.unique_id == BACKUP_EVENT_UNIQUE_ID
            and item.entity_id.startswith("event.")
        ]
        return matches[0] if len(matches) == 1 else None

    @property
    def supported(self) -> bool:
        entity_id = self.resolve_update_entity()
        state = self.hass.states.get(entity_id) if entity_id else None
        return state is not None and state.state not in {"unknown", "unavailable"}

    @property
    def ready(self) -> bool:
        """Return whether the management button may start a new operation."""
        entity_id = self.resolve_update_entity()
        state = self.hass.states.get(entity_id) if entity_id else None
        return (
            state is not None
            and state.state not in {"unknown", "unavailable"}
            and state.attributes.get("in_progress") is not True
        )

    async def _wait_for_state(
        self,
        entity_id: str,
        predicate: Callable[[State], bool],
        timeout_seconds: float,
    ) -> State:
        queue: asyncio.Queue[State | None] = asyncio.Queue()

        def _state_changed(event: Any) -> None:
            if event.data.get("entity_id") == entity_id:
                queue.put_nowait(event.data.get("new_state"))

        unsubscribe = self.hass.bus.async_listen("state_changed", _state_changed)
        try:
            state = self.hass.states.get(entity_id)
            if state is None or state.state == "unavailable":
                raise _StateUnavailableError
            if predicate(state):
                return state
            try:
                async with asyncio.timeout(timeout_seconds):
                    while True:
                        state = await queue.get()
                        if state is None or state.state == "unavailable":
                            raise _StateUnavailableError
                        if predicate(state):
                            return state
            except TimeoutError as err:
                raise _StateTimeoutError from err
        finally:
            unsubscribe()

    async def _wait_for_backup_event(
        self,
        queue: asyncio.Queue[State | BaseException | None],
        predicate: Callable[[State], bool],
        timeout_seconds: float,
    ) -> State:
        """Wait for a newly observed backup event or a service failure."""
        try:
            async with asyncio.timeout(timeout_seconds):
                while True:
                    item = await queue.get()
                    if isinstance(item, BaseException):
                        raise _BackupServiceError from item
                    if item is None or item.state == "unavailable":
                        raise _StateUnavailableError
                    if predicate(item):
                        return item
        except TimeoutError as err:
            raise _StateTimeoutError from err

    async def _async_create_verified_backup(
        self, backup_entity: str, baseline: str, context: Context | None
    ) -> None:
        """Create a backup while observing its new start and terminal events."""
        queue: asyncio.Queue[State | BaseException | None] = asyncio.Queue()

        def _state_changed(event: Any) -> None:
            if event.data.get("entity_id") == backup_entity:
                queue.put_nowait(event.data.get("new_state"))

        unsubscribe = self.hass.bus.async_listen("state_changed", _state_changed)

        async def _call_backup_service() -> None:
            try:
                await self.hass.services.async_call(
                    "backup", "create_automatic", blocking=True, context=context
                )
            except Exception as err:
                queue.put_nowait(err)
                raise

        service_task = self.hass.async_create_task(
            _call_backup_service(), "HealthPlanet Safe Update backup"
        )
        try:
            started = await self._wait_for_backup_event(
                queue,
                lambda state: state.state != baseline
                and state.attributes.get("event_type") in {"in_progress", "failed"},
                self._backup_start_timeout,
            )
            if started.attributes.get("event_type") == "failed":
                raise _BackupServiceError

            self._set_stage(STAGE_WAITING_FOR_BACKUP)
            completed = await self._wait_for_backup_event(
                queue,
                lambda state: state.state != started.state
                and state.attributes.get("event_type") in {"completed", "failed"},
                self._backup_completion_timeout,
            )
            if completed.attributes.get("event_type") != "completed":
                raise _BackupServiceError
            try:
                async with asyncio.timeout(self._backup_completion_timeout):
                    await asyncio.shield(service_task)
            except TimeoutError as err:
                raise _StateTimeoutError from err
            except Exception as err:
                raise _BackupServiceError from err
        finally:
            unsubscribe()
            if not service_task.done():
                service_task.cancel()
            await asyncio.gather(service_task, return_exceptions=True)

    async def _notify(self, result: str, context: Context | None = None) -> None:
        chinese = str(getattr(self.hass.config, "language", "en")).startswith("zh")
        messages = {
            RESULT_NO_UPDATE: (
                "HealthPlanet 已是最新版本。" if chinese else "HealthPlanet is already up to date."
            ),
            RESULT_BACKUP_FAILED: (
                "Home Assistant 備份未成功完成，HealthPlanet 安全更新已取消。"
                if chinese
                else (
                    "HealthPlanet Safe Update was canceled because the Home Assistant "
                    "backup did not complete successfully."
                )
            ),
            RESULT_BACKUP_TIMEOUT: (
                "Home Assistant 備份逾時，HealthPlanet 安全更新已取消。"
                if chinese
                else "The Home Assistant backup timed out. HealthPlanet Safe Update was canceled."
            ),
            RESULT_UPDATE_FAILED: (
                "HealthPlanet 更新未成功完成；Home Assistant 未重新啟動。"
                if chinese
                else (
                    "HealthPlanet update did not complete successfully. Home Assistant "
                    "was not restarted."
                )
            ),
            RESULT_UPDATE_TIMEOUT: (
                "HealthPlanet 更新逾時；Home Assistant 未重新啟動。"
                if chinese
                else "HealthPlanet update timed out. Home Assistant was not restarted."
            ),
            RESULT_UNSUPPORTED: (
                "找不到可用的 HealthPlanet HACS update entity；資料同步不受影響。"
                if chinese
                else (
                    "No usable HealthPlanet HACS update entity was found. Health data "
                    "synchronization is unaffected."
                )
            ),
            RESULT_BUSY: (
                "HealthPlanet 安全更新已在執行中。"
                if chinese
                else "HealthPlanet Safe Update is already running."
            ),
            RESULT_RESTART_FAILED: (
                "HealthPlanet 已更新，但 Home Assistant 無法自動重新啟動；請手動重新啟動。"
                if chinese
                else (
                    "HealthPlanet was updated, but Home Assistant could not restart "
                    "automatically. Restart it manually."
                )
            ),
            RESULT_INSTALLATION_DRIFT: (
                "HACS 顯示的 HealthPlanet 版本與實際安裝檔案不一致；安全更新未開始。"
                if chinese
                else (
                    "The HealthPlanet version reported by HACS does not match the "
                    "installed files. Safe Update was not started."
                )
            ),
            RESULT_INSTALLATION_INVALID: (
                "無法安全驗證 HealthPlanet 實際安裝檔案；安全更新未開始。"
                if chinese
                else (
                    "The installed HealthPlanet files could not be verified safely. "
                    "Safe Update was not started."
                )
            ),
            RESULT_HACS_METADATA_STALE: (
                "HealthPlanet 偵測到 GitHub 已有較新版本，但 HACS 的更新資訊尚未同步。"
                "請前往 HACS 的 HealthPlanet repository，執行「Update information」後"
                "再試一次安全更新。"
                if chinese
                else (
                    "HealthPlanet found a newer GitHub release, but HACS update metadata "
                    "has not synchronized yet. Open the HealthPlanet repository in HACS, "
                    "run Update information, and then try Safe Update again."
                )
            ),
            RESULT_SUCCESS: (
                "HealthPlanet 已成功更新。請重新啟動 Home Assistant 以載入新版本。"
                if chinese
                else (
                    "HealthPlanet was updated successfully. Restart Home Assistant to "
                    "load the new version."
                )
            ),
        }
        if result == RESULT_UPDATE_FAILED and self.last_error_id in {
            "installation_version_mismatch",
            "installation_manifest_missing",
            "installation_manifest_invalid",
        }:
            messages[RESULT_UPDATE_FAILED] = (
                "HACS 顯示 HealthPlanet 已更新，但實際安裝檔案版本不一致。"
                "Home Assistant 未重新啟動。請檢查 HACS 安裝狀態。"
                if chinese
                else (
                    "HACS reports HealthPlanet as updated, but the installed-file "
                    "version does not match. Home Assistant was not restarted. "
                    "Check the HACS installation status."
                )
            )
        try:
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "notification_id": NOTIFICATION_ID,
                    "title": "HealthPlanet Safe Update",
                    "message": messages[result],
                },
                blocking=True,
                context=context,
            )
        except Exception:
            # Notification delivery must never weaken the fail-closed update policy.
            return

    async def async_run(self, *, restart_after_update: bool, context: Context | None = None) -> str:
        """Run a user-initiated Safe Update and return a privacy-safe result."""
        if self._lock.locked():
            await self._notify(RESULT_BUSY, context)
            return RESULT_BUSY

        async with self._lock:
            self.last_error_id = None
            self._set_stage(STAGE_RESOLVING)
            update_entity = self.resolve_update_entity()
            if update_entity is None:
                await self._notify(RESULT_UNSUPPORTED, context)
                return self._finish(RESULT_UNSUPPORTED)
            update_state = self.hass.states.get(update_entity)
            if update_state is None or update_state.state in {"unknown", "unavailable"}:
                await self._notify(RESULT_UNSUPPORTED, context)
                return self._finish(RESULT_UNSUPPORTED)
            disk_before = await self.async_capture_versions(update_state, check_github=True)
            if disk_before.error_id is not None:
                self.last_error_id = disk_before.error_id
                await self._notify(RESULT_INSTALLATION_INVALID, context)
                return self._finish(RESULT_INSTALLATION_INVALID)
            if not self.version_consistent:
                self.last_error_id = "hacs_metadata_disk_version_mismatch"
                await self._notify(RESULT_INSTALLATION_DRIFT, context)
                return self._finish(RESULT_INSTALLATION_DRIFT)
            if self.update_metadata_status == STATUS_HACS_METADATA_STALE:
                self.last_error_id = "hacs_update_metadata_stale"
                await self._notify(RESULT_HACS_METADATA_STALE, context)
                return self._finish(RESULT_HACS_METADATA_STALE)
            if update_state.state == "off":
                await self._notify(RESULT_NO_UPDATE, context)
                return self._finish(RESULT_NO_UPDATE, STAGE_COMPLETED)
            expected_version = update_state.attributes.get("latest_version")
            installed_before = update_state.attributes.get("installed_version")
            if (
                update_state.state != "on"
                or not isinstance(expected_version, str)
                or not expected_version
                or not isinstance(installed_before, str)
                or not installed_before
                or versions_equal(installed_before, expected_version)
                or update_state.attributes.get("in_progress") is True
            ):
                await self._notify(RESULT_UPDATE_FAILED, context)
                return self._finish(RESULT_UPDATE_FAILED)

            backup_entity = self.resolve_backup_entity()
            if backup_entity is None:
                await self._notify(RESULT_BACKUP_FAILED, context)
                return self._finish(RESULT_BACKUP_FAILED)
            backup_state = self.hass.states.get(backup_entity)
            if backup_state is None or backup_state.state == "unavailable":
                await self._notify(RESULT_BACKUP_FAILED, context)
                return self._finish(RESULT_BACKUP_FAILED)
            backup_baseline = backup_state.state

            self._set_stage(STAGE_CREATING_BACKUP)
            try:
                await self._async_create_verified_backup(backup_entity, backup_baseline, context)
            except _StateTimeoutError:
                await self._notify(RESULT_BACKUP_TIMEOUT, context)
                return self._finish(RESULT_BACKUP_TIMEOUT)
            except (_BackupServiceError, _StateUnavailableError):
                await self._notify(RESULT_BACKUP_FAILED, context)
                return self._finish(RESULT_BACKUP_FAILED)

            update_state = self.hass.states.get(update_entity)
            if (
                update_state is None
                or update_state.state != "on"
                or not versions_equal(
                    update_state.attributes.get("latest_version"), expected_version
                )
                or not versions_equal(
                    update_state.attributes.get("installed_version"), installed_before
                )
                or update_state.attributes.get("in_progress") is True
            ):
                await self._notify(RESULT_UPDATE_FAILED, context)
                return self._finish(RESULT_UPDATE_FAILED)

            self._set_stage(STAGE_UPDATING)
            try:
                await self.hass.services.async_call(
                    "update",
                    "install",
                    {"version": expected_version},
                    blocking=True,
                    target={"entity_id": update_entity},
                    context=context,
                )
            except Exception:
                await self._notify(RESULT_UPDATE_FAILED, context)
                return self._finish(RESULT_UPDATE_FAILED)

            self._set_stage(STAGE_VERIFYING_UPDATE)
            try:
                installed = await self._wait_for_state(
                    update_entity,
                    lambda state: state.state in {"off", "unknown", "unavailable"}
                    and state.attributes.get("in_progress") is not True,
                    self._install_timeout,
                )
            except _StateTimeoutError:
                await self._notify(RESULT_UPDATE_TIMEOUT, context)
                return self._finish(RESULT_UPDATE_TIMEOUT)
            except _StateUnavailableError:
                await self._notify(RESULT_UPDATE_FAILED, context)
                return self._finish(RESULT_UPDATE_FAILED)
            if installed.state != "off" or not versions_equal(
                installed.attributes.get("installed_version"), expected_version
            ):
                await self._notify(RESULT_UPDATE_FAILED, context)
                return self._finish(RESULT_UPDATE_FAILED)

            disk_after = await self.async_capture_versions(installed)
            if disk_after.error_id is not None or not versions_equal(
                disk_after.version, expected_version
            ):
                self.last_error_id = disk_after.error_id or "installation_version_mismatch"
                await self._notify(RESULT_UPDATE_FAILED, context)
                return self._finish(RESULT_UPDATE_FAILED)

            if not restart_after_update:
                await self._notify(RESULT_SUCCESS, context)
                return self._finish(RESULT_SUCCESS, STAGE_COMPLETED)

            self._set_stage(STAGE_RESTARTING)
            self._finish(RESULT_SUCCESS, STAGE_RESTARTING)
            await asyncio.sleep(self._restart_delay)
            try:
                await self.hass.services.async_call(
                    "homeassistant", "restart", blocking=False, context=context
                )
            except Exception:
                await self._notify(RESULT_RESTART_FAILED, context)
                return self._finish(RESULT_RESTART_FAILED)
            return RESULT_SUCCESS


def get_safe_update_manager(hass: HomeAssistant) -> SafeUpdateManager:
    """Return the integration-wide single-flight manager."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    manager = domain_data.get(DATA_SAFE_UPDATE_MANAGER)
    if not isinstance(manager, SafeUpdateManager):
        manager = domain_data[DATA_SAFE_UPDATE_MANAGER] = SafeUpdateManager(hass)
    return manager
