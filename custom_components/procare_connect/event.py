"""One event entity per child that fires for each new activity."""

from __future__ import annotations

import asyncio

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import EVENT_TYPES
from .coordinator import ProcareConfigEntry, ProcareCoordinator
from .entity import ProcareKidEntity, async_setup_kid_entities
from .models import ProcareEvent

PARALLEL_UPDATES = 0

# Gap between events of one batch. Home Assistant before 2026.10 could give events fired in
# the same millisecond the same state timestamp, and state triggers with to/not_to then see
# only the last one.
EVENT_SPACING = 0.01  # seconds

ACTIVITY = EventEntityDescription(
    key="activity",
    translation_key="activity",
    event_types=EVENT_TYPES,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProcareConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the activity event entities."""

    def factory(coordinator: ProcareCoordinator, kid_id: str) -> list[ProcareActivityEvent]:
        return [ProcareActivityEvent(coordinator, kid_id, ACTIVITY)]

    async_setup_kid_entities(entry, async_add_entities, factory)


class ProcareActivityEvent(ProcareKidEntity, EventEntity):
    """Fires bottle, diaper, potty, nap, nap_end, sign_in, ... events."""

    def __init__(
        self, coordinator: ProcareCoordinator, kid_id: str, description: EventEntityDescription
    ) -> None:
        """Start after the current refresh: its events, if any, predate this entity."""
        super().__init__(coordinator, kid_id, description)
        self._generation = coordinator.data.generation
        self._pending: list[ProcareEvent] = []
        self._firing: asyncio.Task[None] | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Queue this child's events from a new successful refresh, oldest first."""
        data = self.coordinator.data
        mine: list[ProcareEvent] = []
        if data.generation != self._generation:
            # A failed refresh re-notifies listeners with the old data; don't fire twice.
            self._generation = data.generation
            mine = [e for e in data.events if e.kid_id == self.kid_id]
        if not mine:
            super()._handle_coordinator_update()
            return
        self._pending.extend(mine)
        if self._firing is None:
            self._firing = self.coordinator.config_entry.async_create_task(
                self.hass, self._fire_pending(), f"{self.entity_id} events"
            )

    async def _fire_pending(self) -> None:
        """Fire queued events one by one, a little apart."""
        try:
            while self._pending:
                event = self._pending.pop(0)
                self._trigger_event(event.event_type, event.attributes)
                self.async_write_ha_state()
                if self._pending:
                    await asyncio.sleep(EVENT_SPACING)
        finally:
            self._firing = None

    async def async_will_remove_from_hass(self) -> None:
        """Drop queued events when the entity goes away."""
        self._pending.clear()
        if self._firing is not None:
            self._firing.cancel()
        await super().async_will_remove_from_hass()
