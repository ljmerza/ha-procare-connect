"""Diagnostics for Procare Connect.

Built from an allowlist: counts and field names only. No raw payloads, names, ids, comments,
staff, classrooms, URLs or credentials ever go into the download.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
from .coordinator import ProcareConfigEntry

TO_REDACT = {CONF_EMAIL, CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ProcareConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    kids: list[dict[str, Any]] = []
    if data:
        for index, kid_data in enumerate(data.kids.values(), start=1):
            by_type = Counter(a.activity_type for a in kid_data.activities)
            data_keys: dict[str, set[str]] = {}
            for act in kid_data.activities:
                data_keys.setdefault(act.activity_type, set()).update(act.data)
            kids.append(
                {
                    "child": f"child_{index}",
                    "signed_in": kid_data.kid.is_signed_in,
                    "activities": len(kid_data.activities),
                    "counts_by_type": dict(sorted(by_type.items())),
                    "data_keys_by_type": {t: sorted(k) for t, k in sorted(data_keys.items())},
                }
            )
    last_exception = coordinator.last_exception
    return {
        "entry": {
            "version": entry.version,
            # Only the stored keys survive; their values are redacted.
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "scan_interval_minutes": entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_exception": type(last_exception).__name__ if last_exception else None,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds() if coordinator.update_interval else None
            ),
            "generation": data.generation if data else None,
            "day": data.day.isoformat() if data else None,
            "events_last_refresh": len(data.events) if data else None,
            "children": len(data.kids) if data else 0,
        },
        "children": kids,
    }
