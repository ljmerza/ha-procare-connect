"""Shared fixtures. All data is synthetic (see tests/fixtures and test_fixtures_clean.py)."""

from __future__ import annotations

from collections.abc import Generator
import copy
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion

from custom_components.procare_connect import const, event as event_platform
from custom_components.procare_connect.api import LoginResult, ProcareClient
from custom_components.procare_connect.const import DOMAIN
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

FIXTURES = Path(__file__).parent / "fixtures"

ALEX = "00000000-0000-4000-8000-000000000001"
SAM = "00000000-0000-4000-8000-000000000002"
USER_ID = "00000000-0000-4000-8000-000000000090"
EMAIL = "parent@example.invalid"
HOST = "https://api-school.example.procareconnect.invalid"
TIME_ZONE = "America/New_York"
# 2026-01-15 16:00 in New York (EST, UTC-5).
NOW = "2026-01-15T21:00:00+00:00"


def load(name: str) -> Any:
    """Load a JSON fixture."""
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load custom_components/procare_connect."""


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Serialize registry entries and states the way Home Assistant's own tests do."""
    return snapshot.use_extension(HomeAssistantSnapshotExtension)


@pytest.fixture(autouse=True)
def no_request_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Don't wait between requests or between batched events (the loop clock is frozen)."""
    monkeypatch.setattr(const, "REQUEST_GAP", 0)
    monkeypatch.setattr(event_platform, "EVENT_SPACING", 0)


@pytest.fixture
async def local_time(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """US units, New York time, frozen at 2026-01-15 16:00 local."""
    await hass.config.async_set_time_zone(TIME_ZONE)
    hass.config.units = US_CUSTOMARY_SYSTEM
    freezer.move_to(NOW)
    return freezer


class FakeProcare:
    """In-memory Procare account behind patched ProcareClient methods."""

    def __init__(self) -> None:
        """Start with the fixture day."""
        self.kids: list[dict[str, Any]] = load("kids.json")["kids"]
        self.activities: dict[str, list[dict[str, Any]]] = {
            ALEX: load("activities_alex.json"),
            SAM: load("activities_sam.json"),
        }
        self.user_id: str | None = USER_ID
        self.login = AsyncMock(side_effect=self._login)
        self.get_kids = AsyncMock(side_effect=self._kids)
        self.get_activities = AsyncMock(side_effect=self._activities)

    async def _login(self) -> LoginResult:
        return LoginResult(user_id=self.user_id, base_url=f"{HOST}/api/web/")

    async def _kids(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.kids)

    async def _activities(self, kid_id: str, day: Any) -> list[dict[str, Any]]:
        return copy.deepcopy(self.activities.get(kid_id, []))

    def add(self, kid_id: str, activity: dict[str, Any]) -> None:
        """Add an activity to a child's day."""
        self.activities.setdefault(kid_id, []).append(activity)

    def find(self, kid_id: str, activity_id: str) -> dict[str, Any]:
        """Return a stored activity so a test can edit it."""
        return next(a for a in self.activities[kid_id] if a["id"] == activity_id)


@pytest.fixture
def procare() -> Generator[FakeProcare]:
    """Patch the client's network methods with a fake account."""
    fake = FakeProcare()
    with (
        patch.object(ProcareClient, "async_login", fake.login),
        patch.object(ProcareClient, "async_get_kids", fake.get_kids),
        patch.object(ProcareClient, "async_get_activities", fake.get_activities),
    ):
        yield fake


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A Procare Connect entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=EMAIL,
        unique_id=USER_ID,
        entry_id="01JTESTENTRY0000000000000",
        data={CONF_EMAIL: EMAIL, CONF_PASSWORD: "test-password"},
    )


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant,
    local_time: FrozenDateTimeFactory,
    procare: FakeProcare,
    config_entry: MockConfigEntry,
) -> MockConfigEntry:
    """Set up the integration with the fixture day."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


def activity(
    n: int,
    kind: str,
    hm: str,
    data: dict[str, Any] | None = None,
    *,
    day: str = "2026-01-15",
    comment: str = "",
    activiable: dict[str, Any] | None = None,
    activiable_type: str | None = None,
) -> dict[str, Any]:
    """Build a synthetic activity record."""
    return {
        "id": f"00000000-0000-4000-8000-{n:012d}",
        "activity_type": f"{kind}_activity",
        "activity_date": day,
        "activity_time": f"{day}T{hm}:00.000-05:00",
        "activiable_type": activiable_type,
        "activiable": activiable,
        "data": data or {},
        "comment": comment,
        "staff_present_name": "Teacher Two",
    }
