"""Parsed Procare records and the per-day totals derived from them."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .const import DIRECT_KINDS, MEDIA_KINDS


def parse_oz(value: Any) -> float | None:
    """Procare sends ounces as strings, '' when the field was left blank."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_time(value: Any) -> datetime | None:
    """Parse an ISO timestamp; blank or bad values become None."""
    if not value or not isinstance(value, str):
        return None
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())
    return parsed


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _fmt_oz(value: float) -> str:
    return f"{value:g} oz"


@dataclass(frozen=True, slots=True)
class Kid:
    """A child on the account."""

    id: str
    first_name: str
    is_signed_in: bool

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Kid:
        """Build from a parent/kids/ record."""
        return cls(
            id=str(raw["id"]),
            first_name=_text(raw.get("first_name")) or "Child",
            is_signed_in=bool(raw.get("is_signed_in")),
        )


@dataclass(frozen=True, slots=True)
class Activity:
    """One activity, with photo and video activities already filtered out."""

    id: str
    activity_type: str  # Procare's own value, e.g. "bottle_activity"
    kind: str  # event type: bottle, diaper, potty, nap, sign_in, ..., other
    time: datetime
    data: dict[str, Any]
    comment: str
    staff: str
    section: str  # sign-in/out classroom name
    sign_time: datetime | None  # sign-in/out record's own time

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Activity | None:
        """Build from a parent/activities/ record. Media and timeless records return None."""
        activity_type = _text(raw.get("activity_type")) or "unknown"
        base = activity_type.removesuffix("_activity")
        if base in MEDIA_KINDS or raw.get("activiable_type") == "Photo":
            return None
        when = parse_time(raw.get("activity_time"))
        if when is None:
            return None
        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
        if base == "bathroom":
            kind = "diaper" if _text(data.get("type")).lower() == "diaper" else "potty"
        elif base in DIRECT_KINDS:
            kind = base
        else:
            kind = "other"
        activiable = raw.get("activiable") if isinstance(raw.get("activiable"), dict) else {}
        section = activiable.get("section") if isinstance(activiable.get("section"), dict) else {}
        sign_time = None
        if kind == "sign_in":
            sign_time = parse_time(activiable.get("sign_in_time"))
        elif kind == "sign_out":
            sign_time = parse_time(activiable.get("sign_out_time"))
        return cls(
            id=str(raw["id"]),
            activity_type=activity_type,
            kind=kind,
            time=when,
            data=data,
            comment=_text(raw.get("comment")),
            staff=_text(raw.get("staff_present_name")),
            section=_text(section.get("name")),
            sign_time=sign_time,
        )

    # --- bottle ---
    @property
    def served_oz(self) -> float | None:
        """What was in the bottle."""
        return parse_oz(self.data.get("amount"))

    @property
    def consumed_oz(self) -> float | None:
        """What the child drank, when staff recorded it."""
        return parse_oz(self.data.get("bottle_consumed"))

    @property
    def bottle_oz(self) -> float | None:
        """Consumed when recorded, otherwise served."""
        consumed = self.consumed_oz
        return consumed if consumed is not None else self.served_oz

    # --- diaper / potty ---
    @property
    def sub_type(self) -> str:
        """Wet, BM, Dry, Pee, Tried, ... ('' when blank)."""
        return _text(self.data.get("sub_type"))

    def has_sub(self, word: str) -> bool:
        """Whether the sub type mentions `word` (e.g. 'BM & Wet' counts as both)."""
        return word in self.sub_type.lower()

    # --- nap ---
    @property
    def nap_start(self) -> datetime | None:
        """When the nap started."""
        return parse_time(self.data.get("start_time"))

    @property
    def nap_end(self) -> datetime | None:
        """When the nap ended; None while it's still open."""
        return parse_time(self.data.get("end_time"))

    @property
    def nap_minutes(self) -> int | None:
        """Length of a finished nap."""
        start, end = self.nap_start, self.nap_end
        if start and end and end >= start:
            return round((end - start).total_seconds() / 60)
        return None

    @property
    def event_time(self) -> datetime:
        """The time a sign-in/out actually happened, else the activity time."""
        return self.sign_time or self.time

    @property
    def summary(self) -> str:
        """Short human-readable description."""
        d = self.data
        if self.kind == "bottle":
            parts = []
            if self.served_oz is not None:
                parts.append(f"served {_fmt_oz(self.served_oz)}")
            if self.consumed_oz is not None:
                parts.append(f"drank {_fmt_oz(self.consumed_oz)}")
            text = ", ".join(parts) or "bottle"
            bottle_type = _text(d.get("bottle_type"))
            return f"{text} ({bottle_type})" if bottle_type else text
        if self.kind in ("diaper", "potty"):
            text = " · ".join(x for x in (_text(d.get("type")), self.sub_type) if x)
            return text + (" · cream" if d.get("diaper_cream") is True else "")
        if self.kind == "nap":
            start = self.nap_start
            end = self.nap_end
            fmt = "%-I:%M %p"
            start_s = dt_util.as_local(start).strftime(fmt) if start else ""
            end_s = dt_util.as_local(end).strftime(fmt) if end else "…"
            text = f"{start_s} – {end_s}".strip()
            mins = self.nap_minutes
            return f"{text} ({mins} min)" if mins is not None else text
        if self.kind in ("sign_in", "sign_out"):
            return self.section
        if self.kind == "meal":
            text = ": ".join(x for x in (_text(d.get("type")), _text(d.get("desc"))) if x)
            quantity = _text(d.get("quantity"))
            return f"{text} (ate {quantity.lower()})" if quantity else text
        if self.kind == "learning":
            return _text(d.get("desc")) or self.comment
        return _text(d.get("desc"))

    def event_attributes(self, kid_name: str) -> dict[str, Any]:
        """Attributes sent with the activity event (the same set for nap and nap_end).

        `kid`, `time`, `summary`, the bottle fields, `bathroom_type`, `sub_type`, `start`, `end`
        and `minutes` keep the names of an earlier MQTT bridge so automations carry over.
        """
        attrs: dict[str, Any] = {
            "kid": kid_name,
            "activity_type": self.activity_type,
            "time": self.time.isoformat(),
            "summary": self.summary,
            "comment": self.comment,
            "staff": self.staff,
        }
        d = self.data
        if self.kind == "bottle":
            attrs.update(
                served_oz=self.served_oz,
                consumed_oz=self.consumed_oz,
                bottle_type=_text(d.get("bottle_type")) or None,
            )
        elif self.kind in ("diaper", "potty"):
            attrs.update(
                bathroom_type=_text(d.get("type")) or None,
                sub_type=self.sub_type or None,
            )
            if self.kind == "diaper":
                attrs["diaper_cream"] = d.get("diaper_cream") is True
        elif self.kind == "nap":
            start, end = self.nap_start, self.nap_end
            attrs.update(
                start=start.isoformat() if start else None,
                end=end.isoformat() if end else None,
                minutes=self.nap_minutes,
            )
        elif self.kind == "meal":
            attrs.update(
                meal_type=_text(d.get("type")) or None,
                desc=_text(d.get("desc")) or None,
                quantity=_text(d.get("quantity")) or None,
            )
        elif self.kind == "learning":
            attrs.update(text=_text(d.get("desc")) or self.comment or None)
        elif self.kind in ("sign_in", "sign_out"):
            attrs.update(section=self.section or None)
        return attrs


@dataclass(slots=True)
class DayStats:
    """Totals and last-times for one child's day."""

    bottles_today: int = 0
    bottle_oz_today: float = 0.0
    diapers_today: int = 0
    wet_diapers_today: int = 0
    bm_diapers_today: int = 0
    potty_today: int = 0
    potty_pee_today: int = 0
    potty_bm_today: int = 0
    potty_tried_today: int = 0
    meals_today: int = 0
    naps_today: int = 0
    nap_minutes_today: int = 0
    last_bottle: datetime | None = None
    last_bottle_oz: float | None = None
    last_diaper: datetime | None = None
    last_potty: datetime | None = None
    last_meal: datetime | None = None
    last_meal_attrs: dict[str, Any] = field(default_factory=dict)
    last_nap_end: datetime | None = None
    sign_in_time: datetime | None = None
    sign_out_time: datetime | None = None
    last_activity: datetime | None = None

    @classmethod
    def from_activities(cls, activities: list[Activity]) -> DayStats:
        """Compute from one day's activities (any order)."""
        acts = sorted(activities, key=lambda a: a.time)
        by_kind: dict[str, list[Activity]] = {}
        for act in acts:
            by_kind.setdefault(act.kind, []).append(act)
        bottles = by_kind.get("bottle", [])
        diapers = by_kind.get("diaper", [])
        potty = by_kind.get("potty", [])
        meals = by_kind.get("meal", [])
        naps = by_kind.get("nap", [])
        sign_ins = by_kind.get("sign_in", [])
        sign_outs = by_kind.get("sign_out", [])

        stats = cls(
            bottles_today=len(bottles),
            bottle_oz_today=round(sum(a.bottle_oz or 0 for a in bottles), 1),
            diapers_today=len(diapers),
            wet_diapers_today=sum(1 for a in diapers if a.has_sub("wet")),
            bm_diapers_today=sum(1 for a in diapers if a.has_sub("bm")),
            potty_today=len(potty),
            potty_pee_today=sum(1 for a in potty if a.has_sub("pee") or a.has_sub("wet")),
            potty_bm_today=sum(1 for a in potty if a.has_sub("bm")),
            potty_tried_today=sum(1 for a in potty if a.has_sub("tried")),
            meals_today=len(meals),
            naps_today=len(naps),
            nap_minutes_today=sum(a.nap_minutes or 0 for a in naps),
        )
        if bottles:
            stats.last_bottle = bottles[-1].time
            stats.last_bottle_oz = bottles[-1].bottle_oz
        if diapers:
            stats.last_diaper = diapers[-1].time
        if potty:
            stats.last_potty = potty[-1].time
        if meals:
            meal = meals[-1]
            stats.last_meal = meal.time
            stats.last_meal_attrs = {
                "meal_type": _text(meal.data.get("type")) or None,
                "desc": _text(meal.data.get("desc")) or None,
                "quantity": _text(meal.data.get("quantity")) or None,
            }
        nap_ends = [end for a in naps if (end := a.nap_end) is not None]
        if nap_ends:
            stats.last_nap_end = max(nap_ends)
        if sign_ins:
            stats.sign_in_time = min(a.event_time for a in sign_ins)
        if sign_outs:
            stats.sign_out_time = max(a.event_time for a in sign_outs)
        if acts:
            stats.last_activity = acts[-1].time
        return stats


@dataclass(slots=True)
class KidData:
    """One child's state after a refresh."""

    kid: Kid
    activities: list[Activity]
    stats: DayStats


@dataclass(slots=True)
class ProcareEvent:
    """An activity event to fire on a child's event entity."""

    kid_id: str
    event_type: str
    attributes: dict[str, Any]


@dataclass(slots=True)
class ProcareData:
    """Coordinator data."""

    day: date
    kids: dict[str, KidData]
    # Events found by the refresh that produced this data. `generation` increases with every
    # successful refresh so an entity never fires the same batch twice.
    events: list[ProcareEvent]
    generation: int
