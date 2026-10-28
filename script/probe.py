"""Read-only live check of the Procare API, printing shapes and counts only.

Reads PROCARE_EMAIL / PROCARE_PASSWORD from an env file (default `.env`, gitignored) and makes
three requests, at least a second apart: login, kids, and today's activities for the first
child. Never prints tokens, names, ids, hosts, comments or any other value from the payloads.

    .venv/bin/python script/probe.py [path/to/file.env]

Don't use it to test a wrong password: repeated failed logins can lock the account.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import date
from pathlib import Path
import sys
from typing import Any

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.procare_connect.api import ProcareClient  # noqa: E402


def read_env(path: Path) -> dict[str, str]:
    """KEY=value lines, quotes stripped."""
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip("'\"")
    return env


def shape(value: Any) -> Any:
    """Key names and value types, no values."""
    if isinstance(value, dict):
        return {k: shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return f"list[{len(value)}]"
    return type(value).__name__


async def main(env_path: Path) -> None:
    """Run the probe."""
    env = read_env(env_path)
    bodies: dict[str, Any] = {}
    async with aiohttp.ClientSession() as session:
        client = ProcareClient(session, env["PROCARE_EMAIL"], env["PROCARE_PASSWORD"])
        original = client._request

        async def capture(method: str, url: str, what: str, **kwargs: Any) -> Any:
            status, body, headers = await original(method, url, what, **kwargs)
            bodies[what] = body
            print(f"{what}: HTTP {status}")
            return status, body, headers

        client._request = capture  # type: ignore[method-assign]

        login = await client.async_login()
        raw = bodies.get("login") or {}
        sites = raw.get("sites") or []
        print("login top-level keys:", sorted(raw))
        print("login has user.id:", login.user_id is not None)
        print("user object shape:", shape(raw.get("user")) if "user" in raw else "absent")
        print("sites:", len(sites), "| flagged default:", sum(1 for s in sites if s.get("is_default")))
        print("site keys:", sorted(sites[0]) if sites else [])

        kids = await client.async_get_kids()
        print("kids:", len(kids))
        print("kid keys:", sorted(kids[0]) if kids else [])
        if not kids:
            return

        acts = await client.async_get_activities(kids[0]["id"], date.today())
        page_body = bodies.get("parent/activities/") or {}
        print("activities today (first child):", len(acts))
        print("by type:", dict(Counter(a.get("activity_type") for a in acts)))
        print("activities response keys:", sorted(page_body))
        print("pagination shape:", shape((page_body.get("meta") or {}).get("pagination")))
        print("activity keys:", sorted({k for a in acts for k in a}))


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".env")))
