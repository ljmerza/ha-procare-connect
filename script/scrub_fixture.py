"""Turn a real Procare API capture into a synthetic test fixture.

Real captures go in `captures/` (gitignored) and never leave it. This script reads one, keeps
only allowlisted keys, and replaces every identifying value:

- ids become fake UUIDs `00000000-0000-4000-8000-00000000000N` (consistent within one run);
- first names become Alex, Sam, Jamie, ...; last names "Example";
- comments, descriptions, captions and notes become "Example text.";
- staff become "Teacher One"; classrooms "Classroom A";
- URLs point at `*.example.procareconnect.invalid`; tokens become "test-token-1";
- dates move to 2026-01-15 (time of day and UTC offset are kept).

Any key not listed below is dropped. Enum-like values (activity_type, data.type, sub_type,
quantity, bottle_type, ounces, flags, pagination numbers) are kept as-is.

Before writing, the result is checked with `find_problems` (also used by
tests/test_fixtures_clean.py) and against `.scrub-denylist` (gitignored; one private term per
line: your children's names, your school, staff names). The script refuses to write on a hit.

    python script/scrub_fixture.py captures/activities.json -o tests/fixtures/activities_x.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DENYLIST = ROOT / ".scrub-denylist"

FAKE_DAY = "2026-01-15"
FAKE_HOST = "https://api-school.example.procareconnect.invalid"
FAKE_MEDIA = "https://media.example.procareconnect.invalid/file"
FAKE_NAMES = ["Alex", "Sam", "Jamie", "Riley", "Casey", "Drew"]

CONTAINERS = {
    "kids",
    "activities",
    "sites",
    "meta",
    "pagination",
    "data",
    "activiable",
    "section",
    "user",
}
KEEP = {
    "activity_type",
    "activiable_type",
    "is_signed_in",
    "is_default",
    "is_video",
    "is_active",
    "diaper_cream",
    "type",
    "sub_type",
    "quantity",
    "bottle_type",
    "amount",
    "bottle_consumed",
    "next_page",
    "current_page",
    "prev_page",
    "total_pages",
    "per_page",
    "total",
    "total_count",
}
TIMES = {
    "activity_time",
    "start_time",
    "end_time",
    "sign_in_time",
    "sign_out_time",
    "date",
    "created_at",
}
DATES = {"activity_date"}
IDS = {"id", "current_section_id", "section_id", "activiable_id", "signed_in_section_id"}
TEXT = {"comment", "desc", "caption", "item", "note"}
MEDIA_URLS = {"main_url", "medium_url", "thumb_url", "video_file_url", "photo_url"}

FAKE_UUID = re.compile(r"^00000000-0000-4000-8000-\d{12}$")
UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
URL = re.compile(r"https?://([^/\s\"'<>]+)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
JWT = re.compile(r"eyJ[\w-]{8,}\.[\w-]{8,}")
OPAQUE = re.compile(r"(?<![\w-])[A-Za-z0-9_\-]{32,}(?![\w-])")
TOKEN_VALUE = re.compile(r"\"([\w]*token[\w]*)\"\s*:\s*\"([^\"]*)\"", re.IGNORECASE)
ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}(T.*)$")


def find_problems(text: str) -> list[str]:
    """Things that must never be in a committed fixture or snapshot."""
    problems = []
    for host in URL.findall(text):
        if not host.split(":")[0].endswith(".invalid"):
            problems.append(f"URL host not .invalid: {host}")
    problems += [f"email address: {m}" for m in EMAIL.findall(text)]
    problems += [f"non-fake UUID: {m}" for m in UUID.findall(text) if not FAKE_UUID.match(m)]
    problems += [f"JWT-like token: {m[:12]}..." for m in JWT.findall(text)]
    for key, value in TOKEN_VALUE.findall(text):
        if value and not value.startswith("test-"):
            problems.append(f"token value for {key!r} isn't a test- placeholder")
    # Fake UUIDs are fine, also inside unique ids like "<uuid>_bottles_today".
    without_fakes = re.sub(r"00000000-0000-4000-8000-\d{12}", " ", text)
    for match in OPAQUE.findall(without_fakes):
        if re.search(r"[A-Za-z]", match) and re.search(r"\d", match):
            problems.append(f"opaque token-like string: {match[:12]}...")
    return problems


def denylist_terms(path: Path = DENYLIST) -> list[str]:
    """Private terms from .scrub-denylist (missing file = none)."""
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def denylist_hits(text: str, terms: list[str]) -> list[str]:
    """Denylisted terms present in `text` (case-insensitive, whole words)."""
    lower = text.lower()
    return [
        term
        for term in terms
        if re.search(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])", lower)
    ]


class Scrubber:
    """Allowlist-based scrubber with consistent fake ids and names."""

    def __init__(self) -> None:
        """Start a fresh mapping."""
        self.ids: dict[str, str] = {}
        self.names: dict[str, str] = {}

    def fake_id(self, value: Any) -> Any:
        if value in (None, ""):
            return value
        key = str(value)
        if key not in self.ids:
            self.ids[key] = f"00000000-0000-4000-8000-{len(self.ids) + 1:012d}"
        return self.ids[key]

    def fake_name(self, value: Any) -> str:
        key = str(value)
        if key not in self.names:
            index = len(self.names)
            self.names[key] = FAKE_NAMES[index] if index < len(FAKE_NAMES) else f"Child{index + 1}"
        return self.names[key]

    def scrub(self, value: Any, key: str | None = None, parent: str | None = None) -> Any:
        if isinstance(value, list):
            return [self.scrub(v, key, parent) for v in value]
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                scrubbed = self.scrub_key(k, v, key)
                if scrubbed is not _DROP:
                    out[k] = scrubbed
            return out
        return value

    def scrub_key(self, key: str, value: Any, parent: str | None) -> Any:
        if key in CONTAINERS and isinstance(value, (dict, list)):
            return self.scrub(value, key, parent)
        if isinstance(value, (dict, list)):
            # Unknown nested structures (parents, tags, schedules, ...) are dropped.
            return _DROP
        if key in KEEP:
            return value if not isinstance(value, str) or len(value) <= 40 else _DROP
        if key in TIMES:
            match = ISO_DATETIME.match(value) if isinstance(value, str) else None
            return (
                f"{FAKE_DAY}{match.group(1)}"
                if match
                else (value if value in ("", None) else _DROP)
            )
        if key in DATES:
            return FAKE_DAY if value else value
        if key in IDS or (key == "id" and parent == "user"):
            return self.fake_id(value)
        if key == "first_name":
            return self.fake_name(value)
        if key == "last_name":
            return "Example"
        if key == "name" and parent == "section":
            return "Classroom A"
        if key == "staff_present_name":
            return "Teacher One" if value else ""
        if key in TEXT:
            return "Example text." if value else value
        if key == "base_url":
            return FAKE_HOST
        if key in MEDIA_URLS:
            return f"{FAKE_MEDIA}.jpg" if value else value
        if key == "auth_token":
            return "test-token-1"
        return _DROP


_DROP = object()


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("capture", type=Path, help="real capture (JSON) under captures/")
    parser.add_argument("-o", "--output", type=Path, help="fixture to write (default: stdout)")
    args = parser.parse_args()

    scrubbed = Scrubber().scrub(json.loads(args.capture.read_text()))
    text = json.dumps(scrubbed, indent=2, ensure_ascii=False) + "\n"
    problems = find_problems(text)
    hits = denylist_hits(text, denylist_terms())
    if problems or hits:
        for problem in problems:
            print(f"problem: {problem}", file=sys.stderr)
        if hits:
            print(f"problem: {len(hits)} denylisted term(s) still present", file=sys.stderr)
        return 1
    if args.output:
        args.output.write_text(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
