"""Tests for setup, unload and the coordinator's error handling."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.procare_connect.api import (
    ProcareAuthError,
    ProcareConnectionError,
    ProcareRateLimitError,
)
from custom_components.procare_connect.const import DOMAIN
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant

from .conftest import FakeProcare


async def test_setup_and_unload(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    """The entry loads, creates entities, and unloads."""
    assert setup_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.alex_daycare_bottles_today")
    assert hass.states.get("binary_sensor.alex_daycare_at_daycare")
    assert hass.states.get("event.alex_daycare_activity")
    assert await hass.config_entries.async_unload(setup_entry.entry_id)
    await hass.async_block_till_done()
    assert setup_entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.parametrize("error", [ProcareConnectionError("down"), ProcareRateLimitError(60)])
async def test_setup_not_ready(
    hass: HomeAssistant,
    local_time: FrozenDateTimeFactory,
    procare: FakeProcare,
    config_entry: MockConfigEntry,
    error: Exception,
) -> None:
    """Connection problems at startup retry later."""
    procare.get_kids.side_effect = error
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_no_kids_not_ready(
    hass: HomeAssistant,
    local_time: FrozenDateTimeFactory,
    procare: FakeProcare,
    config_entry: MockConfigEntry,
) -> None:
    """An empty kids list at startup retries later."""
    procare.kids = []
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_auth_failed_starts_reauth(
    hass: HomeAssistant,
    local_time: FrozenDateTimeFactory,
    procare: FakeProcare,
    config_entry: MockConfigEntry,
) -> None:
    """Rejected credentials start the reauth flow."""
    procare.get_kids.side_effect = ProcareAuthError("rejected")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


async def test_runtime_auth_failure_starts_reauth(
    hass: HomeAssistant, setup_entry: MockConfigEntry, procare: FakeProcare
) -> None:
    """A login rejected during polling starts reauth too."""
    procare.get_kids.side_effect = ProcareAuthError("rejected")
    await setup_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


async def test_rate_limit_backoff(
    hass: HomeAssistant, setup_entry: MockConfigEntry, procare: FakeProcare
) -> None:
    """429 sets retry_after: the header when present, else doubling, capped at 30 minutes."""
    coordinator = setup_entry.runtime_data

    async def retry_after(error: Exception) -> float:
        procare.get_kids.side_effect = error
        await coordinator.async_refresh()
        assert not coordinator.last_update_success
        return coordinator.last_exception.retry_after

    assert await retry_after(ProcareRateLimitError(None)) == 60
    assert await retry_after(ProcareRateLimitError(None)) == 120
    assert await retry_after(ProcareRateLimitError(300)) == 300
    assert await retry_after(ProcareRateLimitError(99999)) == 1800
    for _ in range(8):
        last = await retry_after(ProcareRateLimitError(None))
    assert last == 1800
    assert hass.states.get("sensor.alex_daycare_bottles_today").state == STATE_UNAVAILABLE

    # A success resets the back-off.
    procare.get_kids.side_effect = procare._kids
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert await retry_after(ProcareRateLimitError(None)) == 60


async def test_rate_limit_schedules_retry(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    procare: FakeProcare,
    local_time: FrozenDateTimeFactory,
) -> None:
    """After a 429 the next poll waits for retry_after instead of the normal interval."""
    coordinator = setup_entry.runtime_data
    procare.get_kids.side_effect = ProcareRateLimitError(1800)
    local_time.tick(timedelta(minutes=15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert not coordinator.last_update_success

    procare.get_kids.side_effect = procare._kids
    calls = procare.get_kids.call_count
    local_time.tick(timedelta(minutes=16))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert procare.get_kids.call_count == calls  # still backing off

    local_time.tick(timedelta(minutes=15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert procare.get_kids.call_count == calls + 1
    assert coordinator.last_update_success


async def test_polls_on_interval(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    procare: FakeProcare,
    local_time: FrozenDateTimeFactory,
) -> None:
    """Polling runs every 15 minutes by default, at any hour."""
    calls = procare.get_kids.call_count
    local_time.tick(timedelta(minutes=15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert procare.get_kids.call_count == calls + 1
