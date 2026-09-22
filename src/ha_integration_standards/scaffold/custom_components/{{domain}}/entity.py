"""Shared base: every entity hangs off the same device."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import {{class}}Coordinator


class {{class}}Entity(CoordinatorEntity[{{class}}Coordinator]):
    """Base entity for the device."""

    # Without this the device name is repeated in every entity name.
    _attr_has_entity_name = True

    def __init__(self, coordinator: {{class}}Coordinator, key: str) -> None:
        """Tie this entity to one device and one reading."""
        super().__init__(coordinator)
        self._key = key
        # Stable across renames, restarts and reconfigurations - never derive
        # it from the entity name.
        self._attr_unique_id = f"{coordinator.host}_{key}"
        self._attr_translation_key = key

    @property
    def device_info(self) -> DeviceInfo:
        """One device per config entry."""
        data = self.coordinator.data
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.host)},
            manufacturer=MANUFACTURER,
            model=data.get("model") if data else None,
            name=self.coordinator.name,
            sw_version=str(data.get("firmware")) if data else None,
        )

    def _value(self, key: str | None = None) -> Any:
        """Return one reading, or None while nothing has been read yet."""
        data = self.coordinator.data
        return data.get(key or self._key) if data else None
