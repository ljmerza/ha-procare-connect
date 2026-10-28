"""Tests for the activity event entity and the "new activity" rules."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.procare_connect import event as event_platform
from custom_components.procare_connect.api import ProcareConnectionError
from custom_components.procare_connect.const import EVENT_TYPES
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .conftest import ALEX, SAM, FakeProcare, activity

ALEX_EVENT = "event.alex_daycare_activity"
SAM_EVENT = "event.sam_daycare_activity"


@pytest.fixture
def fired(hass: HomeAssistant) -> list[tuple[str, str, dict[str, Any]]]:
    """Record (entity_id, event_type, attributes) for every event fired.

    Coming back from unavailable with the previous event isn't a new event. (Time is frozen in
    tests, so on older Home Assistant a batch shares one timestamp; compare attributes too.)
    """
    events: list[tuple[str, str, dict[str, Any]]] = []
    last: dict[str, tuple[str, dict[str, Any]]] = {}

    @callback
    def _record(event: Event[EventStateChangedData]) -> None:
        new = event.data["new_state"]
        if new is None or new.state in ("unknown", "unavailable"):
            return
        if last.get(new.entity_id) == (new.state, dict(new.attributes)):
            return
        last[new.entity_id] = (new.state, dict(new.attributes))
        attrs = dict(new.attributes)
        events.append((new.entity_id, attrs.pop("event_type"), attrs))

    async_track_state_change_event(hass, [ALEX_EVENT, SAM_EVENT], _record)
    return events


async def _refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_entity(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    """The event entity lists the event types, with no photo or video."""
    state = hass.states.get(ALEX_EVENT)
    assert state.attributes["event_types"] == EVENT_TYPES
    assert "photo" not in EVENT_TYPES
    assert "video" not in EVENT_TYPES
    assert "bathroom" not in EVENT_TYPES


async def test_no_burst_on_first_refresh(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fired: list
) -> None:
    """Activities already there at startup are backlog: no events, now or on the next poll."""
    assert hass.states.get(ALEX_EVENT).state == "unknown"
    await _refresh(hass, setup_entry)
    assert fired == []


async def test_new_activities_fire_in_time_order(
    hass: HomeAssistant, setup_entry: MockConfigEntry, procare: FakeProcare, fired: list
) -> None:
    """New activities fire oldest first, whatever order Procare lists them in."""
    procare.add(
        ALEX,
        activity(501, "bottle", "15:58", {"amount": "4", "bottle_consumed": "", "bottle_type": ""}),
    )
    procare.add(
        ALEX,
        activity(
            502, "bathroom", "15:55", {"type": "Diaper", "sub_type": "Wet", "diaper_cream": False}
        ),
    )
    procare.add(SAM, activity(503, "bathroom", "15:56", {"type": "Potty", "sub_type": "Pee"}))
    await _refresh(hass, setup_entry)
    # Oldest first per child (children's batches may interleave).
    assert [e[1] for e in fired if e[0] == ALEX_EVENT] == ["diaper", "bottle"]
    assert [e[1] for e in fired if e[0] == SAM_EVENT] == ["potty"]
    # Already seen: nothing more on the next poll.
    await _refresh(hass, setup_entry)
    assert len(fired) == 3
    assert hass.states.get(ALEX_EVENT).attributes["event_type"] == "bottle"


async def test_batch_is_spaced(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    procare: FakeProcare,
    fired: list,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Events of one batch go out a little apart, so each gets its own timestamp."""
    marker = 0.0123
    monkeypatch.setattr(event_platform, "EVENT_SPACING", marker)
    pauses: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay: float, *args: Any) -> Any:
        if delay == marker:
            pauses.append(delay)
            delay = 0
        return await real_sleep(delay, *args)

    for n, hm in ((561, "15:50"), (562, "15:51"), (563, "15:52")):
        procare.add(ALEX, activity(n, "note", hm, {"desc": f"Note {n}"}))
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    await _refresh(hass, setup_entry)
    monkeypatch.setattr(asyncio, "sleep", real_sleep)
    assert [e[2]["summary"] for e in fired] == ["Note 561", "Note 562", "Note 563"]
    assert len(pauses) == 2


async def test_compat_attribute_names(
    hass: HomeAssistant, setup_entry: MockConfigEntry, procare: FakeProcare, fired: list
) -> None:
    """Attribute names that existing automations rely on."""
    procare.add(
        ALEX,
        activity(
            511,
            "bottle",
            "15:50",
            {"amount": "5", "bottle_consumed": "4.5", "bottle_type": "Formula"},
        ),
    )
    procare.add(
        ALEX,
        activity(
            512, "bathroom", "15:51", {"type": "Diaper", "sub_type": "BM", "diaper_cream": True}
        ),
    )
    procare.add(ALEX, activity(513, "bathroom", "15:52", {"type": "Potty", "sub_type": "Pee"}))
    procare.add(
        ALEX,
        activity(
            514,
            "nap",
            "15:53",
            {
                "start_time": "2026-01-15T15:00:00.000-05:00",
                "end_time": "2026-01-15T15:45:00.000-05:00",
            },
        ),
    )
    await _refresh(hass, setup_entry)
    by_type = {e[1]: e[2] for e in fired}

    common = {"kid", "time", "summary", "activity_type", "comment", "staff"}
    bottle = by_type["bottle"]
    assert common | {"served_oz", "consumed_oz", "bottle_type"} <= bottle.keys()
    assert bottle["kid"] == "Alex"
    assert bottle["time"] == "2026-01-15T15:50:00-05:00"
    assert (bottle["served_oz"], bottle["consumed_oz"], bottle["bottle_type"]) == (
        5.0,
        4.5,
        "Formula",
    )
    assert bottle["summary"] == "served 5 oz, drank 4.5 oz (Formula)"
    assert bottle["staff"] == "Teacher Two"

    diaper = by_type["diaper"]
    assert common | {"bathroom_type", "sub_type", "diaper_cream"} <= diaper.keys()
    assert (diaper["bathroom_type"], diaper["sub_type"], diaper["diaper_cream"]) == (
        "Diaper",
        "BM",
        True,
    )

    potty = by_type["potty"]
    assert common | {"bathroom_type", "sub_type"} <= potty.keys()
    assert (potty["bathroom_type"], potty["sub_type"]) == ("Potty", "Pee")
    assert "diaper_cream" not in potty

    nap = by_type["nap"]
    assert common | {"start", "end", "minutes"} <= nap.keys()
    assert nap["minutes"] == 45
    assert nap["start"] == "2026-01-15T15:00:00-05:00"


async def test_meal_learning_sign_attributes(
    hass: HomeAssistant, setup_entry: MockConfigEntry, procare: FakeProcare, fired: list
) -> None:
    """Meal, learning and sign-out details ride along."""
    section = {"id": "00000000-0000-4000-8000-000000000080", "name": "Classroom A"}
    procare.add(
        SAM,
        activity(521, "meal", "15:40", {"type": "PM Snack", "desc": "Crackers", "quantity": "All"}),
    )
    procare.add(SAM, activity(522, "learning", "15:41", comment="Sang songs."))
    procare.add(SAM, activity(523, "mood", "15:42", {"desc": "Happy"}))
    procare.add(
        SAM,
        activity(
            524,
            "sign_out",
            "15:43",
            activiable={"section": section, "sign_out_time": "2026-01-15T15:43:00.000-05:00"},
        ),
    )
    procare.add(SAM, activity(525, "something_new", "15:44", {"desc": "Unknown kind"}))
    await _refresh(hass, setup_entry)
    by_type = {e[1]: e[2] for e in fired}
    assert set(by_type) == {"meal", "learning", "mood", "sign_out", "other"}
    meal = by_type["meal"]
    assert (meal["meal_type"], meal["desc"], meal["quantity"]) == ("PM Snack", "Crackers", "All")
    assert meal["summary"] == "PM Snack: Crackers (ate all)"
    assert by_type["learning"]["text"] == "Sang songs."
    assert by_type["learning"]["comment"] == "Sang songs."
    assert by_type["mood"]["summary"] == "Happy"
    assert by_type["sign_out"]["section"] == "Classroom A"
    assert by_type["other"]["activity_type"] == "something_new_activity"


async def test_nap_end(
    hass: HomeAssistant, setup_entry: MockConfigEntry, procare: FakeProcare, fired: list
) -> None:
    """A seen nap that gets its end time fires nap_end once."""
    nap = procare.find(SAM, "00000000-0000-4000-8000-000000000153")
    nap["data"]["end_time"] = "2026-01-15T14:00:00.000-05:00"
    await _refresh(hass, setup_entry)
    assert [(e[0], e[1]) for e in fired] == [(SAM_EVENT, "nap_end")]
    attrs = fired[0][2]
    assert attrs["end"] == "2026-01-15T14:00:00-05:00"
    assert attrs["minutes"] == 90
    assert attrs["kid"] == "Sam"
    await _refresh(hass, setup_entry)
    assert len(fired) == 1
    assert hass.states.get("sensor.sam_daycare_nap_minutes_today").state == "90"


async def test_new_finished_nap_is_nap_only(
    hass: HomeAssistant, setup_entry: MockConfigEntry, procare: FakeProcare, fired: list
) -> None:
    """A nap first seen with an end time fires nap, not nap_end."""
    procare.add(
        ALEX,
        activity(
            531,
            "nap",
            "15:00",
            {
                "start_time": "2026-01-15T15:00:00.000-05:00",
                "end_time": "2026-01-15T15:30:00.000-05:00",
            },
        ),
    )
    await _refresh(hass, setup_entry)
    assert [e[1] for e in fired] == ["nap"]


async def test_photos_ignored(
    hass: HomeAssistant, setup_entry: MockConfigEntry, procare: FakeProcare, fired: list
) -> None:
    """Photo and video activities never fire and never count."""
    procare.add(
        ALEX,
        activity(
            541,
            "photo",
            "15:50",
            activiable={"id": "00000000-0000-4000-8000-000000000341", "caption": "x"},
            activiable_type="Photo",
        ),
    )
    procare.add(ALEX, activity(542, "video", "15:51"))
    await _refresh(hass, setup_entry)
    assert fired == []
    assert hass.states.get("sensor.alex_daycare_last_activity").state == "2026-01-15T20:45:00+00:00"


async def test_failed_refresh_does_not_refire(
    hass: HomeAssistant, setup_entry: MockConfigEntry, procare: FakeProcare, fired: list
) -> None:
    """A failed poll re-notifies entities with old data; events must not repeat."""
    procare.add(ALEX, activity(551, "note", "15:50", {"desc": "Example note."}))
    await _refresh(hass, setup_entry)
    assert len(fired) == 1
    procare.get_kids.side_effect = ProcareConnectionError("down")
    await _refresh(hass, setup_entry)
    assert hass.states.get(ALEX_EVENT).state == "unavailable"
    procare.get_kids.side_effect = procare._kids
    await _refresh(hass, setup_entry)
    assert [e[1] for e in fired] == ["note"]
    assert hass.states.get(ALEX_EVENT).attributes["event_type"] == "note"


async def test_midnight_rollover(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    procare: FakeProcare,
    local_time: FrozenDateTimeFactory,
    fired: list,
) -> None:
    """Just after midnight the counters reset; the first activity of the morning fires."""
    procare.activities = {ALEX: [], SAM: []}
    local_time.move_to("2026-01-16T05:00:30+00:00")  # 00:00:30 in New York
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert procare.get_activities.call_args.args[1].isoformat() == "2026-01-16"
    bottles = hass.states.get("sensor.alex_daycare_bottles_today")
    assert bottles.state == "0"
    assert bottles.attributes["last_reset"] == "2026-01-16T00:00:00-05:00"
    assert hass.states.get("sensor.alex_daycare_last_bottle").state == "unknown"
    assert fired == []

    procare.add(ALEX, activity(601, "sign_in", "07:30", day="2026-01-16"))
    local_time.tick(timedelta(hours=7))
    await _refresh(hass, setup_entry)
    assert [(e[0], e[1]) for e in fired] == [(ALEX_EVENT, "sign_in")]
