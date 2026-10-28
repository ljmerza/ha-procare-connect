"""Whether each child is signed in at daycare."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ProcareConfigEntry, ProcareCoordinator
from .entity import ProcareKidEntity, async_setup_kid_entities

PARALLEL_UPDATES = 0

AT_DAYCARE = BinarySensorEntityDescription(
    key="at_daycare",
    translation_key="at_daycare",
    device_class=BinarySensorDeviceClass.PRESENCE,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProcareConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the presence sensors."""

    def factory(coordinator: ProcareCoordinator, kid_id: str) -> list[ProcareAtDaycare]:
        return [ProcareAtDaycare(coordinator, kid_id, AT_DAYCARE)]

    async_setup_kid_entities(entry, async_add_entities, factory)


class ProcareAtDaycare(ProcareKidEntity, BinarySensorEntity):
    """On while Procare says the child is signed in."""

    @property
    def is_on(self) -> bool | None:
        """Procare's is_signed_in flag."""
        if (data := self.kid_data) is None:
            return None
        return data.kid.is_signed_in
