"""{{name}}."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .coordinator import {{class}}Coordinator

# The typed alias is what the runtime-data rule asks for: the entry carries the
# coordinator, and every module that touches entry.runtime_data knows its type.
type {{class}}ConfigEntry = ConfigEntry[{{class}}Coordinator]

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(
    hass: HomeAssistant, entry: {{class}}ConfigEntry
) -> bool:
    """Set up a device from a config entry."""
    coordinator = {{class}}Coordinator(hass, entry, entry.data[CONF_HOST])

    # Fail here rather than letting entities appear broken: Home Assistant
    # retries a ConfigEntryNotReady with backoff and tells the user why.
    try:
        await coordinator.async_config_entry_first_refresh()
    except TimeoutError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"host": entry.data[CONF_HOST]},
        ) from err

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Anything started during setup is unregistered here, not in unload.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: {{class}}ConfigEntry
) -> None:
    """Reload so changed options take effect."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: {{class}}ConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
