"""Tests for the sensors and the presence binary sensor."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from homeassistant.const import Platform, __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import ALEX, SAM, FakeProcare, activity

# The registry's snapshot format changes between Home Assistant releases; the snapshots are
# recorded with the version pinned in requirements_test.txt.
SNAPSHOT_HA = "2026.10."


@pytest.mark.skipif(
    not HA_VERSION.startswith(SNAPSHOT_HA), reason=f"snapshots are recorded on {SNAPSHOT_HA}x"
)
@pytest.mark.parametrize("platform", [Platform.SENSOR, Platform.BINARY_SENSOR])
async def test_snapshot(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
    local_time: FrozenDateTimeFactory,
    procare: FakeProcare,
    config_entry: MockConfigEntry,
    platform: Platform,
) -> None:
    """Every entity, its registry entry and state for the fixture day."""
    config_entry.add_to_hass(hass)
    with patch("custom_components.procare_connect.PLATFORMS", [platform]):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    await snapshot_platform(hass, entity_registry, snapshot, config_entry.entry_id)


def _state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state.state


async def test_alex_counters(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    """Totals from the fixture day; photos and videos count nowhere."""
    expected = {
        "bottles_today": "2",
        "bottle_oz_today": "10.0",  # 4 consumed + 6 served (consumed left blank)
        "diapers_today": "2",
        "wet_diapers_today": "2",  # Wet, BM & Wet
        "bm_diapers_today": "1",
        "potty_today": "2",
        "potty_pee_today": "1",
        "potty_bm_today": "0",
        "potty_tried_today": "1",
        "meals_today": "1",
        "naps_today": "1",
        "nap_minutes_today": "90",
        "last_bottle_oz": "6.0",
    }
    for key, value in expected.items():
        assert _state(hass, f"sensor.alex_daycare_{key}") == value, key


async def test_sam_split_and_open_nap(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    """Potty BM isn't a diaper; an open nap counts as a nap but adds no minutes."""
    assert _state(hass, "sensor.sam_daycare_diapers_today") == "0"
    assert _state(hass, "sensor.sam_daycare_bm_diapers_today") == "0"
    assert _state(hass, "sensor.sam_daycare_potty_today") == "1"
    assert _state(hass, "sensor.sam_daycare_potty_bm_today") == "1"
    assert _state(hass, "sensor.sam_daycare_naps_today") == "1"
    assert _state(hass, "sensor.sam_daycare_nap_minutes_today") == "0"
    assert _state(hass, "sensor.sam_daycare_last_nap_ended") == "unknown"
    assert _state(hass, "sensor.sam_daycare_bottles_today") == "0"
    assert _state(hass, "sensor.sam_daycare_last_bottle") == "unknown"
    assert _state(hass, "sensor.sam_daycare_last_bottle_oz") == "unknown"


async def test_timestamps(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    """Sign-in uses the sign-in record's own time; others use the activity time."""
    assert _state(hass, "sensor.alex_daycare_sign_in_time") == "2026-01-15T12:44:00+00:00"
    assert _state(hass, "sensor.alex_daycare_sign_out_time") == "unknown"
    assert _state(hass, "sensor.alex_daycare_last_bottle") == "2026-01-15T19:00:00+00:00"
    assert _state(hass, "sensor.alex_daycare_last_nap_ended") == "2026-01-15T18:30:00+00:00"
    assert _state(hass, "sensor.alex_daycare_last_activity") == "2026-01-15T20:45:00+00:00"
    assert _state(hass, "sensor.sam_daycare_sign_out_time") == "2026-01-15T20:00:00+00:00"
    meal = hass.states.get("sensor.alex_daycare_last_meal")
    assert meal.state == "2026-01-15T16:00:00+00:00"
    assert meal.attributes["meal_type"] == "Lunch"
    assert meal.attributes["desc"] == "Pasta and peas"
    assert meal.attributes["quantity"] == "Most"


async def test_presence(
    hass: HomeAssistant, setup_entry: MockConfigEntry, procare: FakeProcare
) -> None:
    """at_daycare follows is_signed_in."""
    assert _state(hass, "binary_sensor.alex_daycare_at_daycare") == "on"
    assert _state(hass, "binary_sensor.sam_daycare_at_daycare") == "off"
    procare.kids[1]["is_signed_in"] = True
    await setup_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert _state(hass, "binary_sensor.sam_daycare_at_daycare") == "on"


async def test_last_reset_and_state_class(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    """Daily counters are state_class total with last_reset at local midnight."""
    state = hass.states.get("sensor.alex_daycare_bottles_today")
    assert state.attributes["state_class"] == "total"
    assert datetime.fromisoformat(state.attributes["last_reset"]) == datetime.fromisoformat(
        "2026-01-15T00:00:00-05:00"
    )
    oz = hass.states.get("sensor.alex_daycare_last_bottle_oz")
    assert "state_class" not in oz.attributes
    assert "last_reset" not in oz.attributes


async def test_counts_can_go_down(
    hass: HomeAssistant, setup_entry: MockConfigEntry, procare: FakeProcare
) -> None:
    """An activity deleted upstream lowers the count."""
    procare.activities[ALEX] = [
        a for a in procare.activities[ALEX] if a["id"] != procare.activities[ALEX][1]["id"]
    ]
    await setup_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert _state(hass, "sensor.alex_daycare_bottles_today") == "1"
    assert _state(hass, "sensor.alex_daycare_bottle_oz_today") == "6.0"


async def test_oz_fallback_and_blank(
    hass: HomeAssistant, setup_entry: MockConfigEntry, procare: FakeProcare
) -> None:
    """Consumed wins over served; blank strings are no value at all."""
    procare.add(
        SAM,
        activity(901, "bottle", "14:00", {"amount": "", "bottle_consumed": "", "bottle_type": ""}),
    )
    procare.add(SAM, activity(902, "bottle", "14:30", {"amount": "7", "bottle_consumed": "3.5"}))
    await setup_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert _state(hass, "sensor.sam_daycare_bottles_today") == "2"
    assert _state(hass, "sensor.sam_daycare_bottle_oz_today") == "3.5"
    assert _state(hass, "sensor.sam_daycare_last_bottle_oz") == "3.5"
