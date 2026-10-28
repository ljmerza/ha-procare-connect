"""Constants for Procare Connect."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "procare_connect"

AUTH_URL: Final = "https://online-auth.procareconnect.com/sessions/"

CONF_SCAN_INTERVAL: Final = "scan_interval"
# Hourly by default and never faster than 15 minutes: Procare's terms restrict automated access (README).
DEFAULT_SCAN_INTERVAL: Final = 60  # minutes
MIN_SCAN_INTERVAL: Final = 15
MAX_SCAN_INTERVAL: Final = 180

# Procare answers bursts with 429. Every request waits at least this long after the last one.
REQUEST_GAP: Final = 1.0  # seconds
REQUEST_TIMEOUT: Final = 30  # seconds
MAX_PAGES: Final = 50  # activities come 15 per page; this is a runaway guard

# Back-off after a 429 when Procare sends no usable Retry-After, doubled per consecutive 429.
RATE_LIMIT_BACKOFF: Final = 60  # seconds
RATE_LIMIT_MAX_BACKOFF: Final = 30 * 60  # seconds

MANUFACTURER: Final = "Procare"
MODEL: Final = "Daily activities"

# Event types of the activity event entity. Photo and video activities are dropped entirely;
# bathroom activities are split into diaper and potty by their data.type.
EVENT_TYPES: Final = [
    "bottle",
    "diaper",
    "potty",
    "nap",
    "nap_end",
    "sign_in",
    "sign_out",
    "meal",
    "learning",
    "mood",
    "medication",
    "incident",
    "note",
    "other",
]

# Procare activity kinds (activity_type minus "_activity") that map to an event type of the
# same name. Anything else that isn't media or bathroom becomes "other".
DIRECT_KINDS: Final = frozenset(
    {
        "bottle",
        "nap",
        "sign_in",
        "sign_out",
        "meal",
        "learning",
        "mood",
        "medication",
        "incident",
        "note",
    }
)
MEDIA_KINDS: Final = frozenset({"photo", "video"})
