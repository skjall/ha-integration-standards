"""A throwaway integration to point the checks at."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

MANIFEST = {
    "domain": "acme",
    "name": "Acme",
    "version": "1.0.0",
    "codeowners": ["@someone"],
    "documentation": "https://github.com/someone/home-assistant-acme",
    "issue_tracker": "https://github.com/someone/home-assistant-acme/issues",
    "integration_type": "device",
    "iot_class": "local_polling",
    "config_flow": True,
    "quality_scale": "custom",
}

INIT = '''"""Acme."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryNotReady

type AcmeConfigEntry = ConfigEntry[AcmeCoordinator]

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass, entry):
    raise ConfigEntryNotReady
    entry.runtime_data = None


async def async_unload_entry(hass, entry):
    return True
'''

ENTITY = '''"""Base."""
from homeassistant.helpers.device_registry import DeviceInfo


class AcmeEntity:
    _attr_has_entity_name = True

    def __init__(self):
        self._attr_unique_id = "x"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo()

    @property
    def available(self) -> bool:
        return True
'''

SENSOR = '''"""Sensor."""
from homeassistant.components.sensor import SensorEntityDescription

PARALLEL_UPDATES = 0

SENSORS = (SensorEntityDescription(key="temperature", translation_key="temperature"),)
'''

COORDINATOR = '''"""Coordinator."""
from homeassistant.exceptions import HomeAssistantError


async def send(self):
    raise HomeAssistantError(translation_key="command_failed")
'''


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A minimal integration that holds every rule it claims."""
    root = tmp_path / "home-assistant-acme"
    package = root / "custom_components" / "acme"
    (package / "translations").mkdir(parents=True)

    (package / "manifest.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    (package / "__init__.py").write_text(INIT, encoding="utf-8")
    (package / "entity.py").write_text(ENTITY, encoding="utf-8")
    (package / "sensor.py").write_text(SENSOR, encoding="utf-8")
    (package / "coordinator.py").write_text(COORDINATOR, encoding="utf-8")
    (package / "config_flow.py").write_text(
        '"""Flow."""\nerrors = {}\n', encoding="utf-8"
    )

    strings = {
        "entity": {"sensor": {"temperature": {"name": "Temperature"}}},
        "exceptions": {"command_failed": {"message": "no"}},
    }
    (package / "strings.json").write_text(json.dumps(strings), encoding="utf-8")
    (package / "translations" / "en.json").write_text(
        json.dumps(strings), encoding="utf-8"
    )
    (package / "icons.json").write_text(
        json.dumps(
            {"entity": {"sensor": {"temperature": {"default": "mdi:thermometer"}}}}
        ),
        encoding="utf-8",
    )
    (package / "quality_scale.yaml").write_text(
        yaml.safe_dump(
            {
                "rules": {
                    "common_modules": "done",
                    "runtime_data": "done",
                    "config_flow": "done",
                    "test_before_configure": "done",
                    "test_before_setup": "done",
                    "config_entry_unloading": "done",
                    "has_entity_name": "done",
                    "entity_unique_id": "done",
                    "parallel_updates": "done",
                    "entity_unavailable": "done",
                    "action_exceptions": "done",
                    "entity_translations": "done",
                    "icon_translations": "done",
                    "exception_translations": "done",
                    "integration_owner": "done",
                    "devices": "done",
                }
            }
        ),
        encoding="utf-8",
    )
    return root
