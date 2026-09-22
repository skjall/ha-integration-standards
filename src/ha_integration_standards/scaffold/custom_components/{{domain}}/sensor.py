"""Sensor platform.

One platform module per platform, each with its own PARALLEL_UPDATES and its
own descriptions. Copy this file for button, number, switch and the rest.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import {{class}}ConfigEntry
from .entity import {{class}}Entity

# The coordinator already serialises the reads, so the platform does not have
# to. A platform that talks to the device itself sets a real limit here.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class {{class}}SensorDescription(SensorEntityDescription):
    """A reading, and how to get it out of the coordinator data."""

    value: Callable[[dict[str, Any]], Any] = lambda data: None


SENSORS: tuple[{{class}}SensorDescription, ...] = (
    {{class}}SensorDescription(
        # The key is the translation key: the name comes from strings.json and
        # the icon from icons.json. Never pass icon= or name= here.
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value=lambda data: data.get("temperature"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: {{class}}ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        {{class}}Sensor(coordinator, description) for description in SENSORS
    )


class {{class}}Sensor({{class}}Entity, SensorEntity):
    """A single reading."""

    entity_description: {{class}}SensorDescription

    def __init__(
        self, coordinator: Any, description: {{class}}SensorDescription
    ) -> None:
        """Bind the description to the entity."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the reading."""
        data = self.coordinator.data
        return self.entity_description.value(data) if data else None

    @property
    def available(self) -> bool:
        """Say so when the reading itself is missing, not just the device."""
        return super().available and self.native_value is not None
