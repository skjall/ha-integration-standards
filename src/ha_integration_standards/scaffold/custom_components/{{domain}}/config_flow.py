"""Config flow: user, discovery, reconfigure."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST

from .const import DOMAIN


class {{class}}ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for {{name}}."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a device by hand."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # unique-config-entry: one entry per device, and abort rather than
            # letting the same device in twice.
            await self.async_set_unique_id(user_input[CONF_HOST])
            self._abort_if_unique_id_configured()

            # test-before-configure: talk to the device before writing the
            # entry, and report the failure in the form instead of creating an
            # entry that can never work.
            if error := await self._async_try_connect(user_input[CONF_HOST]):
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=user_input[CONF_HOST], data=user_input
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user move the device to a new address."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            if error := await self._async_try_connect(user_input[CONF_HOST]):
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str}
            ),
            errors=errors,
        )

    async def _async_try_connect(self, host: str) -> str | None:
        """Return an error key from strings.json, or None when reachable."""
        raise NotImplementedError("try to reach the device here")
