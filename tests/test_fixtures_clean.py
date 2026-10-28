"""Guards for a public repository: no real data in fixtures, snapshots or tracked files."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "scrub_fixture", ROOT / "script" / "scrub_fixture.py"
)
scrub_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scrub_fixture)

DATA_FILES = sorted(
    [
        *ROOT.joinpath("tests", "fixtures").rglob("*"),
        *ROOT.joinpath("tests", "snapshots").rglob("*"),
    ]
)


@pytest.mark.parametrize("path", [p for p in DATA_FILES if p.is_file()], ids=lambda p: p.name)
def test_fixture_is_synthetic(path: Path) -> None:
    """Only .invalid URLs, fake UUIDs, no emails and no tokens."""
    assert scrub_fixture.find_problems(path.read_text()) == []


def test_checker_catches_real_looking_data() -> None:
    """The checker itself flags each kind of leak."""
    leaks = [
        '"url": "https://schools.somewhere.example.com/x"',
        '"email": "someone@example.com"',
        '"id": "3f2a9c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b"',
        '"auth_token": "abc"',
        '"x": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0"',
        '"x": "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7"',
    ]
    for leak in leaks:
        assert scrub_fixture.find_problems(leak), leak


def test_scrubber_output_is_clean() -> None:
    """A real-shaped capture comes out synthetic, keeping the shape and enums."""
    capture = {
        "auth_token": "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7",
        "user": {"id": 4242, "email": "someone@example.com"},
        "sites": [
            {
                "base_url": "https://api-school.tenant.procareconnect.com",
                "is_default": True,
                "name": "Some School",
            }
        ],
        "kids": [
            {
                "id": "3f2a9c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b",
                "first_name": "Realname",
                "last_name": "Family",
                "is_signed_in": True,
                "parents": [{"email": "someone@example.com"}],
                "dob": "2024-02-03",
            }
        ],
        "activities": [
            {
                "id": "9e8d7c6b-5a49-4382-b1a0-f9e8d7c6b5a4",
                "activity_type": "bathroom_activity",
                "activity_date": "2025-10-01",
                "activity_time": "2025-10-01T09:15:00.000-04:00",
                "comment": "Private comment",
                "staff_present_name": "Real Teacher",
                "data": {
                    "type": "Diaper",
                    "sub_type": "BM & Wet",
                    "diaper_cream": True,
                    "desc": "",
                },
                "activiable": {
                    "section": {"id": "1a2b3c4d-1a2b-4c3d-8e9f-0a1b2c3d4e5f", "name": "Room 3"}
                },
                "activity_participants": ["3f2a9c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b"],
            }
        ],
        "meta": {"pagination": {"next_page": None, "per_page": 15}},
    }
    scrubbed = scrub_fixture.Scrubber().scrub(capture)
    text = json.dumps(scrubbed)
    assert scrub_fixture.find_problems(text) == []
    for private in (
        "Realname",
        "Family",
        "Private comment",
        "Real Teacher",
        "Room 3",
        "Some School",
        "tenant",
        "2024-02-03",
    ):
        assert private not in text, private
    act = scrubbed["activities"][0]
    assert act["activity_time"] == "2026-01-15T09:15:00.000-04:00"
    assert act["data"] == {
        "type": "Diaper",
        "sub_type": "BM & Wet",
        "diaper_cream": True,
        "desc": "",
    }
    assert scrubbed["kids"][0]["first_name"] == "Alex"
    assert scrub_fixture.FAKE_UUID.match(scrubbed["kids"][0]["id"])
    assert scrubbed["user"]["id"] != scrubbed["kids"][0]["id"]
    assert "email" not in scrubbed["user"]
    assert "parents" not in scrubbed["kids"][0]
    assert scrubbed["meta"] == {"pagination": {"next_page": None, "per_page": 15}}


def _repo_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
            capture_output=True,
            check=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return [ROOT / name for name in out.split("\0") if name and (ROOT / name).is_file()]


def test_no_denylisted_terms() -> None:
    """Private terms in the local, gitignored .scrub-denylist appear in no committable file
    and no commit message. Skipped where the denylist doesn't exist (CI, other clones)."""
    terms = scrub_fixture.denylist_terms()
    if not terms:
        pytest.skip("no .scrub-denylist")
    hits = []
    for path in _repo_files():
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        if found := scrub_fixture.denylist_hits(text, terms):
            hits.append(f"{path.relative_to(ROOT)}: {len(found)} term(s)")
    log = subprocess.run(
        ["git", "log", "--all", "--format=%B"], cwd=ROOT, capture_output=True, text=True
    ).stdout
    if found := scrub_fixture.denylist_hits(log, terms):
        hits.append(f"commit messages: {len(found)} term(s)")
    assert hits == []
