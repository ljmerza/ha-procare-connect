"""Daily counters and last-activity times per child."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import ProcareConfigEntry, ProcareCoordinator
from .entity import ProcareKidEntity, async_setup_kid_entities
from .models import DayStats

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ProcareSensorDescription(SensorEntityDescription):
    """Describes a per-child sensor."""

    value_fn: Callable[[DayStats], Any]
    attrs_fn: Callable[[DayStats], dict[str, Any]] | None = None
    daily_total: bool = False  # state_class total, reset at local midnight


def _counter(key: str, **kwargs: Any) -> ProcareSensorDescription:
    return ProcareSensorDescription(
        key=key,
        translation_key=key,
        state_class=SensorStateClass.TOTAL,
        daily_total=True,
        value_fn=lambda s: getattr(s, key),
        **kwargs,
    )


def _timestamp(key: str, attr: str | None = None, **kwargs: Any) -> ProcareSensorDescription:
    return ProcareSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda s: getattr(s, attr or key),
        **kwargs,
    )


SENSORS: tuple[ProcareSensorDescription, ...] = (
    _counter("bottles_today"),
    _counter(
        "bottle_oz_today",
        device_class=SensorDeviceClass.VOLUME,
        native_unit_of_measurement=UnitOfVolume.FLUID_OUNCES,
        suggested_display_precision=1,
    ),
    _counter("diapers_today"),
    _counter("wet_diapers_today"),
    _counter("bm_diapers_today"),
    _counter("potty_today"),
    _counter("potty_pee_today"),
    _counter("potty_bm_today"),
    _counter("potty_tried_today"),
    _counter("meals_today"),
    _counter("naps_today"),
    _counter(
        "nap_minutes_today",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
    ),
    _timestamp("last_bottle"),
    ProcareSensorDescription(
        key="last_bottle_oz",
        translation_key="last_bottle_oz",
        device_class=SensorDeviceClass.VOLUME,
        native_unit_of_measurement=UnitOfVolume.FLUID_OUNCES,
        suggested_display_precision=1,
        value_fn=lambda s: s.last_bottle_oz,
    ),
    _timestamp("last_diaper"),
    _timestamp("last_potty"),
    _timestamp("last_meal", attrs_fn=lambda s: s.last_meal_attrs),
    _timestamp("last_nap_end"),
    _timestamp("sign_in_time"),
    _timestamp("sign_out_time"),
    _timestamp("last_activity"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProcareConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""

    def factory(coordinator: ProcareCoordinator, kid_id: str) -> list[ProcareSensor]:
        return [ProcareSensor(coordinator, kid_id, description) for description in SENSORS]

    async_setup_kid_entities(entry, async_add_entities, factory)


class ProcareSensor(ProcareKidEntity, SensorEntity):
    """A per-child sensor."""

    entity_description: ProcareSensorDescription

    @property
    def native_value(self) -> Any:
        """Current value."""
        if (data := self.kid_data) is None:
            return None
        return self.entity_description.value_fn(data.stats)

    @property
    def last_reset(self) -> datetime | None:
        """Daily totals start over at local midnight."""
        if not self.entity_description.daily_total:
            return None
        return dt_util.start_of_local_day(self.coordinator.data.day)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Extra attributes (last meal details)."""
        if self.entity_description.attrs_fn is None or (data := self.kid_data) is None:
            return None
        return self.entity_description.attrs_fn(data.stats)
