"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_HOST
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.{{domain}}.const import DOMAIN

HOST = "192.0.2.10"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Make the custom integration loadable in every test."""


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A device that is already set up."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=HOST,
        unique_id=HOST,
        data={CONF_HOST: HOST},
    )


@pytest.fixture
def mock_device() -> Generator[AsyncMock]:
    """A device that answers every read with plausible values."""
    client = AsyncMock()
    client.read.return_value = {"temperature": 21.5, "model": "Kettle", "firmware": "1.0"}
    with patch(
        "custom_components.{{domain}}.coordinator.connect", return_value=client
    ):
        yield client


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Skip the actual setup while testing the flow."""
    with patch(
        "custom_components.{{domain}}.async_setup_entry", return_value=True
    ) as mocked:
        yield mocked
