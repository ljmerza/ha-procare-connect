"""Async client for the Procare Connect parent web API.

This is the same private API the parent web portal uses. It isn't documented or supported by
Procare. Error messages never carry response bodies, tokens or hosts: they can end up in logs
and issue reports.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
import logging
import time
from typing import Any

import aiohttp

from . import const

_LOGGER = logging.getLogger(__name__)

# Login answers these when the email or password is wrong.
_AUTH_REJECTED = {400, 401, 403, 404, 422}


class ProcareError(Exception):
    """Base error for the Procare client."""


class ProcareAuthError(ProcareError):
    """The credentials were rejected."""


class ProcareConnectionError(ProcareError):
    """Procare couldn't be reached or answered with a server error."""


class ProcareResponseError(ProcareError):
    """Procare answered with something the client doesn't understand."""


class ProcareRateLimitError(ProcareError):
    """Procare answered 429."""

    def __init__(self, retry_after: float | None) -> None:
        """Store the server's Retry-After, in seconds, when it sent one."""
        super().__init__("Procare rate limit (HTTP 429)")
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class LoginResult:
    """What the client keeps from a login."""

    user_id: str | None
    base_url: str


def _retry_after(headers: Any) -> float | None:
    """Parse Retry-After as seconds; HTTP-date values are ignored."""
    try:
        value = float(headers.get("Retry-After", ""))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


class ProcareClient:
    """Talks to the Procare parent API with one account."""

    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        """Set up the client; nothing is sent until the first request."""
        self._session = session
        self._email = email
        self._password = password
        self._token: str | None = None
        self._base: str | None = None
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def _throttle(self) -> None:
        """Keep at least REQUEST_GAP seconds between requests."""
        wait = self._last_request + const.REQUEST_GAP - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request = time.monotonic()

    async def _request(
        self,
        method: str,
        url: str,
        what: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any, Any]:
        """Send one request. Returns (status, parsed JSON or None, response headers)."""
        await self._throttle()
        try:
            async with self._session.request(
                method,
                url,
                params=params,
                json=json,
                headers={"Accept": "application/json", **(headers or {})},
                timeout=aiohttp.ClientTimeout(total=const.REQUEST_TIMEOUT),
            ) as resp:
                status = resp.status
                resp_headers = resp.headers
                body = None
                if 200 <= status < 300:
                    try:
                        body = await resp.json(content_type=None)
                    except ValueError as err:
                        raise ProcareResponseError(f"{what}: response isn't JSON") from err
        except TimeoutError as err:
            raise ProcareConnectionError(f"{what}: timed out") from err
        except aiohttp.ClientError as err:
            raise ProcareConnectionError(f"{what}: {type(err).__name__}") from err
        return status, body, resp_headers

    async def async_login(self) -> LoginResult:
        """Log in and pick the default site (or the first one)."""
        status, body, headers = await self._request(
            "POST",
            const.AUTH_URL,
            "login",
            json={
                "email": self._email,
                "password": self._password,
                "role": "carer",
                "platform": "web",
            },
        )
        if status == 429:
            raise ProcareRateLimitError(_retry_after(headers))
        if status in _AUTH_REJECTED:
            raise ProcareAuthError(f"login rejected (HTTP {status})")
        if status >= 500:
            raise ProcareConnectionError(f"login: HTTP {status}")
        if not 200 <= status < 300:
            raise ProcareResponseError(f"login: HTTP {status}")
        if not isinstance(body, dict):
            raise ProcareResponseError("login: unexpected response")
        token = body.get("auth_token")
        sites = body.get("sites")
        if not token or not isinstance(sites, list) or not sites:
            raise ProcareResponseError("login: no token or no sites in the response")
        site = next((s for s in sites if isinstance(s, dict) and s.get("is_default")), sites[0])
        base_url = site.get("base_url") if isinstance(site, dict) else None
        if not base_url:
            raise ProcareResponseError("login: site has no base_url")
        user = body.get("user")
        user_id = user.get("id") if isinstance(user, dict) else None
        self._token = token
        self._base = base_url.rstrip("/") + "/api/web/"
        return LoginResult(
            user_id=str(user_id) if user_id not in (None, "") else None,
            base_url=self._base,
        )

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET an API path. Logs in when needed and once more on 401."""
        async with self._lock:
            if self._token is None:
                await self.async_login()
            relogged = False
            while True:
                assert self._base is not None
                status, body, headers = await self._request(
                    "GET",
                    self._base + path,
                    path,
                    params=params,
                    headers={"Authorization": f"Bearer {self._token}"},
                )
                if status == 401 and not relogged:
                    _LOGGER.debug("Procare token rejected, logging in again")
                    relogged = True
                    self._token = None
                    await self.async_login()
                    continue
                if status == 401:
                    raise ProcareAuthError(f"{path}: HTTP 401 after a fresh login")
                if status == 429:
                    raise ProcareRateLimitError(_retry_after(headers))
                if status >= 500:
                    raise ProcareConnectionError(f"{path}: HTTP {status}")
                if not 200 <= status < 300:
                    raise ProcareResponseError(f"{path}: HTTP {status}")
                if not isinstance(body, dict):
                    raise ProcareResponseError(f"{path}: unexpected response")
                return body

    async def async_get_kids(self) -> list[dict[str, Any]]:
        """Return the account's children."""
        body = await self._get("parent/kids/")
        kids = body.get("kids")
        if not isinstance(kids, list):
            raise ProcareResponseError("parent/kids/: no kids list")
        return [k for k in kids if isinstance(k, dict) and k.get("id")]

    async def async_get_activities(self, kid_id: str, day: date) -> list[dict[str, Any]]:
        """Return all of one child's activities on `day`, following pagination."""
        activities: list[dict[str, Any]] = []
        page: Any = 1
        for _ in range(const.MAX_PAGES):
            body = await self._get(
                "parent/activities/",
                {
                    "activities_filter[date_from]": day.isoformat(),
                    "activities_filter[date_to]": day.isoformat(),
                    "kids_filter[kid_ids][]": kid_id,
                    "page": page,
                },
            )
            items = body.get("activities")
            if not isinstance(items, list):
                raise ProcareResponseError("parent/activities/: no activities list")
            activities.extend(a for a in items if isinstance(a, dict) and a.get("id"))
            meta = body.get("meta")
            pagination = meta.get("pagination") if isinstance(meta, dict) else None
            page = pagination.get("next_page") if isinstance(pagination, dict) else None
            if not page:
                return activities
        _LOGGER.warning("Stopped after %s pages of activities", const.MAX_PAGES)
        return activities
