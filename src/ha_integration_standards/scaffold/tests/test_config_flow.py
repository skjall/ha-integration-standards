"""The flow, which the quality scale wants covered completely."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.{{domain}}.const import DOMAIN

from .conftest import HOST


@pytest.mark.usefixtures("mock_device")
async def test_the_user_adds_a_device(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """A reachable device becomes an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: HOST}


@pytest.mark.usefixtures("mock_device")
async def test_the_same_device_is_not_added_twice(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A device that is already set up aborts the flow."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
