"""Polls Procare and works out which activities are new."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ProcareAuthError, ProcareClient, ProcareError, ProcareRateLimitError
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    RATE_LIMIT_BACKOFF,
    RATE_LIMIT_MAX_BACKOFF,
)
from .models import Activity, DayStats, Kid, KidData, ProcareData, ProcareEvent

type ProcareConfigEntry = ConfigEntry[ProcareCoordinator]

_LOGGER = logging.getLogger(__name__)


class ProcareCoordinator(DataUpdateCoordinator[ProcareData]):
    """Fetches today's activities for every child on the account."""

    config_entry: ProcareConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ProcareConfigEntry, client: ProcareClient
    ) -> None:
        """Set up the coordinator."""
        minutes = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=minutes),
        )
        self.client = client
        # Per child: activity ids seen today, and naps seen without an end time. A child that
        # isn't in `_seen` yet has no baseline: its first fetch only seeds (no backlog burst).
        self._seen: dict[str, set[str]] = {}
        self._open_naps: dict[str, set[str]] = {}
        self._day = dt_util.now().date()
        self._generation = 0
        self._rate_limit_hits = 0

    def _backoff(self, retry_after: float | None) -> float:
        """Seconds until the next try after a 429, capped at 30 minutes."""
        self._rate_limit_hits += 1
        fallback = RATE_LIMIT_BACKOFF * 2 ** (self._rate_limit_hits - 1)
        wait = retry_after if retry_after is not None else fallback
        return float(min(max(wait, RATE_LIMIT_BACKOFF), RATE_LIMIT_MAX_BACKOFF))

    async def _async_update_data(self) -> ProcareData:
        """Fetch the kids list and each kid's activities for today."""
        today = dt_util.now().date()
        try:
            raw_kids = await self.client.async_get_kids()
            if not raw_kids:
                raise UpdateFailed("Procare returned no children")
            fetched: dict[str, tuple[Kid, list[Activity]]] = {}
            for raw in raw_kids:
                kid = Kid.from_api(raw)
                raw_acts = await self.client.async_get_activities(kid.id, today)
                acts = [a for r in raw_acts if (a := Activity.from_api(r)) is not None]
                acts.sort(key=lambda a: a.time)
                fetched[kid.id] = (kid, acts)
        except ProcareAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ProcareRateLimitError as err:
            wait = self._backoff(err.retry_after)
            _LOGGER.warning("Procare rate limit hit, next try in %d s", wait)
            raise UpdateFailed(
                f"Procare rate limit, retrying in {wait:.0f} s", retry_after=wait
            ) from err
        except ProcareError as err:
            raise UpdateFailed(str(err)) from err
        self._rate_limit_hits = 0

        if today != self._day:
            # New day: keep each child's baseline (so the first activity of the morning fires)
            # but forget yesterday's ids.
            self._day = today
            self._seen = {kid_id: set() for kid_id in self._seen}
            self._open_naps = {kid_id: set() for kid_id in self._open_naps}

        events: list[ProcareEvent] = []
        kids: dict[str, KidData] = {}
        for kid_id, (kid, acts) in fetched.items():
            events.extend(self._new_events(kid, acts))
            kids[kid_id] = KidData(kid=kid, activities=acts, stats=DayStats.from_activities(acts))

        self._prune_devices(set(kids))
        self._generation += 1
        return ProcareData(day=today, kids=kids, events=events, generation=self._generation)

    def _new_events(self, kid: Kid, acts: list[Activity]) -> list[ProcareEvent]:
        """Events for activities not seen before, plus naps that just got an end time."""
        kid_id = kid.id
        ids = {a.id for a in acts}
        open_naps = {a.id for a in acts if a.kind == "nap" and a.nap_end is None}
        seen = self._seen.get(kid_id)
        events: list[ProcareEvent] = []
        if seen is not None:
            was_open = self._open_naps.get(kid_id, set())
            new = [a for a in acts if a.id not in seen]
            events.extend(
                ProcareEvent(kid_id, a.kind, a.event_attributes(kid.first_name)) for a in new
            )
            ended = [
                a
                for a in acts
                if a.kind == "nap" and a.id in seen and a.id in was_open and a.nap_end is not None
            ]
            ended.sort(key=lambda a: a.nap_end or a.time)
            events.extend(
                ProcareEvent(kid_id, "nap_end", a.event_attributes(kid.first_name)) for a in ended
            )
        # Ids that disappeared (deleted upstream) are dropped from the set as well.
        self._seen[kid_id] = ids
        self._open_naps[kid_id] = open_naps
        return events

    @callback
    def _prune_devices(self, kid_ids: set[str]) -> None:
        """Detach devices of children that are no longer on the account."""
        dev_reg = dr.async_get(self.hass)
        for device in dr.async_entries_for_config_entry(dev_reg, self.config_entry.entry_id):
            device_kids = {ident for domain, ident in device.identifiers if domain == DOMAIN}
            if device_kids and not device_kids & kid_ids:
                _LOGGER.info("Removing a child that is no longer on the Procare account")
                dev_reg.async_update_device(
                    device.id, remove_config_entry_id=self.config_entry.entry_id
                )
                for kid_id in device_kids:
                    self._seen.pop(kid_id, None)
                    self._open_naps.pop(kid_id, None)

    async def async_midnight(self, _now: datetime) -> None:
        """Refresh just after local midnight so the daily counters reset."""
        await self.async_refresh()
