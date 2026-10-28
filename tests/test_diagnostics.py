"""Tests for diagnostics: counts and field names only."""

from __future__ import annotations

import json

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.procare_connect.diagnostics import async_get_config_entry_diagnostics
from homeassistant.core import HomeAssistant

from .conftest import ALEX, EMAIL, USER_ID, load


async def test_diagnostics(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    """Shape and counts are there; nothing that identifies anyone is."""
    diag = await async_get_config_entry_diagnostics(hass, setup_entry)
    assert diag["entry"]["data"] == {"email": "**REDACTED**", "password": "**REDACTED**"}
    assert diag["entry"]["scan_interval_minutes"] == 15
    assert diag["coordinator"]["last_update_success"] is True
    assert diag["coordinator"]["children"] == 2
    alex = diag["children"][0]
    assert alex["child"] == "child_1"
    assert alex["counts_by_type"]["bathroom_activity"] == 4
    assert "photo_activity" not in alex["counts_by_type"]
    assert alex["data_keys_by_type"]["bottle_activity"] == [
        "amount",
        "bottle_consumed",
        "bottle_type",
        "desc",
    ]

    dumped = json.dumps(diag)
    forbidden = [
        EMAIL,
        "test-password",
        USER_ID,
        ALEX,
        "Alex",
        "Sam",
        "Example",
        "Teacher",
        "Classroom",
        "Pasta",
        "blocks",
        "http",
        "token",
    ]
    for term in forbidden:
        assert term not in dumped, term
    # Every value from the activity payloads is absent (keys are allowed).
    for item in load("activities_alex.json"):
        assert item["id"] not in dumped
        if item["comment"]:
            assert item["comment"] not in dumped
