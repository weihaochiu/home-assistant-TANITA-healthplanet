from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tanita_healthplanet.button import (
    HealthPlanetSafeUpdateButton,
    async_setup_entry,
)
from custom_components.tanita_healthplanet.const import (
    CONF_HACS_UPDATE_ENTITY,
    CONF_HACS_UPDATE_UNIQUE_ID,
    CONF_HISTORY_SYNC_ENABLED,
    CONF_MODE,
    CONF_OFFICIAL_HISTORY_DAYS,
    CONF_OFFICIAL_UPDATE_INTERVAL,
    CONF_RESTART_AFTER_SAFE_UPDATE,
    DOMAIN,
    MODE_OFFICIAL_ONLY,
)
from custom_components.tanita_healthplanet.safe_update import SafeUpdateManager


async def test_three_config_entries_create_exactly_one_repository_button(hass):
    entries = [MockConfigEntry(domain=DOMAIN, title=f"Family {index}") for index in range(3)]
    entities = []
    for entry in entries:
        entry.add_to_hass(hass)
        entry.runtime_data = SimpleNamespace(history_sync=None)
    for entry in entries:
        await async_setup_entry(hass, entry, entities.extend)

    safe_buttons = [
        entity for entity in entities if isinstance(entity, HealthPlanetSafeUpdateButton)
    ]
    assert len(safe_buttons) == 1


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_options_fallback_stores_rename_safe_identity_globally(hass):
    healthplanet_entries = [
        MockConfigEntry(
            domain=DOMAIN,
            title=f"Family {index}",
            data={CONF_MODE: MODE_OFFICIAL_ONLY},
        )
        for index in range(2)
    ]
    for entry in healthplanet_entries:
        entry.add_to_hass(hass)

    hacs_entry = MockConfigEntry(domain="hacs", title="HACS")
    hacs_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    update_entry = registry.async_get_or_create(
        "update",
        "hacs",
        "selected-stable-repository-id",
        suggested_object_id="selected_healthplanet_update",
        config_entry=hacs_entry,
    )

    result = await hass.config_entries.options.async_init(healthplanet_entries[0].entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_OFFICIAL_UPDATE_INTERVAL: 60,
            CONF_HISTORY_SYNC_ENABLED: True,
            CONF_OFFICIAL_HISTORY_DAYS: 90,
            CONF_HACS_UPDATE_ENTITY: update_entry.entity_id,
            CONF_RESTART_AFTER_SAFE_UPDATE: False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    for entry in healthplanet_entries:
        assert entry.options[CONF_HACS_UPDATE_UNIQUE_ID] == "selected-stable-repository-id"
        assert entry.options[CONF_RESTART_AFTER_SAFE_UPDATE] is False

    renamed_id = "update.user_renamed_selected_healthplanet_update"
    registry.async_update_entity(update_entry.entity_id, new_entity_id=renamed_id)
    assert SafeUpdateManager(hass).resolve_update_entity() == renamed_id


async def test_public_registry_discovery_survives_entity_id_rename(hass):
    """Repository identity, not a fixed entity_id, identifies the HACS update."""
    hacs_entry = MockConfigEntry(domain="hacs", title="HACS")
    hacs_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    original = registry.async_get_or_create(
        "update",
        "hacs",
        "synthetic-repository-id",
        suggested_object_id="healthplanet_for_home_assistant_update",
        config_entry=hacs_entry,
    )
    renamed_id = "update.user_renamed_healthplanet_repository"
    registry.async_update_entity(original.entity_id, new_entity_id=renamed_id)
    hass.states.async_set(
        renamed_id,
        "on",
        {
            "installed_version": "0.2.1",
            "latest_version": "0.2.2",
            "release_url": (
                "https://github.com/weihaochiu/home-assistant-TANITA-healthplanet/releases/v0.2.2"
            ),
        },
    )

    assert SafeUpdateManager(hass).resolve_update_entity() == renamed_id


async def test_similarly_named_repository_is_not_auto_discovered(hass):
    """A friendly-name collision cannot select a different repository."""
    hacs_entry = MockConfigEntry(domain="hacs", title="HACS")
    hacs_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    entity = registry.async_get_or_create(
        "update",
        "hacs",
        "different-repository-id",
        suggested_object_id="healthplanet_for_home_assistant_update",
        config_entry=hacs_entry,
    )
    hass.states.async_set(
        entity.entity_id,
        "on",
        {
            "friendly_name": "HealthPlanet for Home Assistant update",
            "release_url": "https://github.com/someone-else/similarly-named-project/releases/v9.9.9",
        },
    )

    assert SafeUpdateManager(hass).resolve_update_entity() is None
