"""Diagnostics for a configured device."""

from __future__ import annotations

from typing import Any

from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import {{class}}ConfigEntry

# Anything that identifies the installation or unlocks the device. Err on the
# side of redacting: a diagnostics file ends up in public issue trackers.
TO_REDACT = {CONF_HOST, CONF_PASSWORD, "serial_number", "token"}


def _redact(data: dict[str, Any]) -> dict[str, Any]:
    return {k: ("**REDACTED**" if k in TO_REDACT else v) for k, v in data.items()}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: {{class}}ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "entry": {
            "data": _redact(dict(entry.data)),
            "options": _redact(dict(entry.options)),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval": str(coordinator.update_interval),
        },
        "data": _redact(coordinator.data) if coordinator.data else None,
    }
