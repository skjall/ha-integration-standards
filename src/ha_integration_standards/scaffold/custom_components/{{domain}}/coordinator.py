"""One coordinator per device; every entity reads from it."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_INTERVAL, DEFAULT_INTERVAL, DOMAIN

if TYPE_CHECKING:
    from . import {{class}}ConfigEntry

_LOGGER = logging.getLogger(__name__)


class {{class}}Coordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch the device state once and hand it to every entity."""

    config_entry: {{class}}ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: {{class}}ConfigEntry, host: str
    ) -> None:
        """Set the polling interval from the options, not from a constant."""
        self.host = host
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_INTERVAL, DEFAULT_INTERVAL)
            ),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Read the device.

        Raise UpdateFailed for anything transient - the coordinator marks the
        entities unavailable and keeps trying. Do not swallow it: an entity
        that keeps showing a stale value is worse than one that says it does
        not know.
        """
        try:
            raise NotImplementedError("read the device here")
        except TimeoutError as err:
            raise UpdateFailed(f"{self.host} did not answer: {err}") from err

    async def async_send_command(self, command: str) -> None:
        """Act on the device.

        A failed action raises HomeAssistantError with a translation_key that
        exists under "exceptions" in strings.json - that is what the user sees,
        and it is the reason TRY003 is switched off in pyproject.toml.
        """
        try:
            raise NotImplementedError("write to the device here")
        except TimeoutError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"command": command},
            ) from err
