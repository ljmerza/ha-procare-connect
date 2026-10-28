"""Tests for the config, reauth and options flows."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.procare_connect.api import (
    ProcareAuthError,
    ProcareConnectionError,
    ProcareRateLimitError,
)
from custom_components.procare_connect.const import CONF_SCAN_INTERVAL, DOMAIN
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import EMAIL, USER_ID, FakeProcare

USER_INPUT = {CONF_EMAIL: f"  {EMAIL} ", CONF_PASSWORD: "test-password"}


async def test_user_flow(hass: HomeAssistant, procare: FakeProcare) -> None:
    """A good login creates the entry, keyed on the Procare user id."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == EMAIL
    assert result["data"] == {CONF_EMAIL: EMAIL, CONF_PASSWORD: "test-password"}
    assert result["result"].unique_id == USER_ID


async def test_user_flow_email_unique_id(hass: HomeAssistant, procare: FakeProcare) -> None:
    """Without a user id in the login response, the lowercased email is the unique id."""
    procare.user_id = None
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: "Parent@Example.invalid", CONF_PASSWORD: "x"}
    )
    await hass.async_block_till_done()
    assert result["result"].unique_id == "parent@example.invalid"


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (ProcareAuthError("rejected"), "invalid_auth"),
        (ProcareConnectionError("down"), "cannot_connect"),
        (ProcareRateLimitError(60), "cannot_connect"),
        (RuntimeError("bug"), "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant, procare: FakeProcare, side_effect: Exception, error: str
) -> None:
    """Login problems show an error, and the form recovers."""
    procare.login.side_effect = side_effect
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    procare.login.side_effect = procare._login
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_no_kids(hass: HomeAssistant, procare: FakeProcare) -> None:
    """An account without children can't be added."""
    procare.kids = []
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["errors"] == {"base": "no_kids"}


async def test_already_configured(
    hass: HomeAssistant, procare: FakeProcare, config_entry: MockConfigEntry
) -> None:
    """The same account can't be added twice."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(
    hass: HomeAssistant, setup_entry: MockConfigEntry, procare: FakeProcare
) -> None:
    """Reauth stores the new password and reloads."""
    result = await setup_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    procare.login.side_effect = ProcareAuthError("rejected")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    procare.login.side_effect = procare._login
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new-password"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert setup_entry.data[CONF_PASSWORD] == "new-password"
    assert setup_entry.data[CONF_EMAIL] == EMAIL


async def test_reauth_wrong_account(
    hass: HomeAssistant, setup_entry: MockConfigEntry, procare: FakeProcare
) -> None:
    """A login that resolves to another account is refused."""
    result = await setup_entry.start_reauth_flow(hass)
    procare.user_id = "00000000-0000-4000-8000-000000000099"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new-password"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert setup_entry.data[CONF_PASSWORD] == "test-password"


async def test_options(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    """Changing the interval reloads the entry with the new interval."""
    assert setup_entry.runtime_data.update_interval.total_seconds() == 60 * 60
    result = await hass.config_entries.options.async_init(setup_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 30}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup_entry.options == {CONF_SCAN_INTERVAL: 30}
    assert setup_entry.runtime_data.update_interval.total_seconds() == 30 * 60
