"""Base entity and per-child entity creation."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import ProcareConfigEntry, ProcareCoordinator
from .models import KidData


class ProcareKidEntity(CoordinatorEntity[ProcareCoordinator]):
    """An entity that belongs to one child's device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ProcareCoordinator,
        kid_id: str,
        description: EntityDescription,
    ) -> None:
        """Bind the entity to a child."""
        super().__init__(coordinator)
        self.entity_description = description
        self.kid_id = kid_id
        self._attr_unique_id = f"{kid_id}_{description.key}"
        kid = coordinator.data.kids[kid_id].kid
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, kid_id)},
            name=f"{kid.first_name} daycare",
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def kid_data(self) -> KidData | None:
        """This child's data from the last successful refresh."""
        return self.coordinator.data.kids.get(self.kid_id)

    @property
    def available(self) -> bool:
        """Available while the last refresh worked and still lists the child."""
        return super().available and self.kid_data is not None


def async_setup_kid_entities(
    entry: ProcareConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[ProcareCoordinator, str], Iterable[Entity]],
) -> None:
    """Add entities for every child now, and for children who show up later."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new_kids() -> None:
        if not coordinator.last_update_success or not coordinator.data:
            return
        current = set(coordinator.data.kids)
        # A child that left and came back gets its entities again.
        known.intersection_update(current)
        new = current - known
        if not new:
            return
        known.update(new)
        async_add_entities([e for kid_id in sorted(new) for e in factory(coordinator, kid_id)])

    _add_new_kids()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_kids))
