"""Stable shared device metadata."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, VERSION


def healthplanet_device_info(entry_id: str, name: str, model: str) -> DeviceInfo:
    """Return the existing family device identity with release metadata."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name=name,
        manufacturer="TANITA",
        model=model,
        sw_version=VERSION,
    )
