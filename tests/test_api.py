"""Tests for the Procare API client."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.procare_connect import const
from custom_components.procare_connect.api import (
    ProcareAuthError,
    ProcareClient,
    ProcareConnectionError,
    ProcareRateLimitError,
    ProcareResponseError,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .conftest import ALEX, EMAIL, HOST, USER_ID, load

AUTH = const.AUTH_URL
KIDS = f"{HOST}/api/web/parent/kids/"
ACTIVITIES = f"{HOST}/api/web/parent/activities/"
DAY = date(2026, 1, 15)


def _client(hass: HomeAssistant) -> ProcareClient:
    return ProcareClient(async_get_clientsession(hass), EMAIL, "test-password")


def _page(items: list, next_page: int | None) -> dict:
    return {"activities": items, "meta": {"pagination": {"next_page": next_page}}}


async def test_login_picks_default_site(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The site flagged is_default wins over the first one."""
    aioclient_mock.post(AUTH, json=load("login.json"))
    result = await _client(hass).async_login()
    assert result.base_url == f"{HOST}/api/web/"
    assert result.user_id == USER_ID
    _, _, body, _ = aioclient_mock.mock_calls[0]
    assert body == {"email": EMAIL, "password": "test-password", "role": "carer", "platform": "web"}


async def test_login_first_site_and_no_user(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Without a default site the first is used; a missing user id is None."""
    aioclient_mock.post(
        AUTH,
        json={"auth_token": "test-token-1", "sites": [{"base_url": HOST + "/"}, {"base_url": "x"}]},
    )
    result = await _client(hass).async_login()
    assert result.base_url == f"{HOST}/api/web/"
    assert result.user_id is None


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, ProcareAuthError),
        (422, ProcareAuthError),
        (500, ProcareConnectionError),
        (302, ProcareResponseError),
    ],
)
async def test_login_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status: int, error: type
) -> None:
    """Login failures map to the client's errors without the body."""
    aioclient_mock.post(AUTH, status=status, text="secret-body test-token-1")
    with pytest.raises(error) as exc:
        await _client(hass).async_login()
    assert "secret-body" not in str(exc.value)


async def test_login_bad_payload(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """A login without a token or sites is a response error."""
    aioclient_mock.post(AUTH, json={"sites": []})
    with pytest.raises(ProcareResponseError):
        await _client(hass).async_login()


async def test_connection_error(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """aiohttp errors and timeouts become connection errors."""
    aioclient_mock.post(AUTH, exc=aiohttp.ClientConnectionError("boom"))
    with pytest.raises(ProcareConnectionError):
        await _client(hass).async_login()
    aioclient_mock.clear_requests()
    aioclient_mock.post(AUTH, exc=TimeoutError())
    with pytest.raises(ProcareConnectionError):
        await _client(hass).async_login()


async def test_kids_sends_bearer(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """The first call logs in, then sends the token."""
    aioclient_mock.post(AUTH, json=load("login.json"))
    aioclient_mock.get(KIDS, json=load("kids.json"))
    kids = await _client(hass).async_get_kids()
    assert [k["first_name"] for k in kids] == ["Alex", "Sam"]
    _, _, _, headers = aioclient_mock.mock_calls[1]
    assert headers["Authorization"] == "Bearer test-token-1"


async def test_activities_pagination(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """next_page is followed until it's empty."""
    items = load("activities_alex.json")
    aioclient_mock.post(AUTH, json=load("login.json"))
    aioclient_mock.get(ACTIVITIES, params={"page": "2"}, json=_page(items[8:], None))
    aioclient_mock.get(ACTIVITIES, params={"page": "1"}, json=_page(items[:8], 2))
    result = await _client(hass).async_get_activities(ALEX, DAY)
    assert [a["id"] for a in result] == [a["id"] for a in items]
    first = aioclient_mock.mock_calls[1][1]
    assert first.query["activities_filter[date_from]"] == "2026-01-15"
    assert first.query["activities_filter[date_to]"] == "2026-01-15"
    assert first.query["kids_filter[kid_ids][]"] == ALEX
    assert first.query["page"] == "1"
    assert aioclient_mock.mock_calls[2][1].query["page"] == "2"


async def test_relogin_once_on_401(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An expired token gets one fresh login."""
    calls = 0

    async def kids(method, url, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return AiohttpClientMockResponse(method, url, status=401)
        return AiohttpClientMockResponse(method, url, json=load("kids.json"))

    aioclient_mock.post(AUTH, json=load("login.json"))
    aioclient_mock.get(KIDS, side_effect=kids)
    assert len(await _client(hass).async_get_kids()) == 2
    logins = [c for c in aioclient_mock.mock_calls if c[0] == "POST"]
    assert len(logins) == 2


async def test_401_after_relogin_is_auth_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A second 401 in a row means the account can't read the API."""
    aioclient_mock.post(AUTH, json=load("login.json"))
    aioclient_mock.get(KIDS, status=401)
    with pytest.raises(ProcareAuthError):
        await _client(hass).async_get_kids()


async def test_rate_limit(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """429 raises with the server's Retry-After."""
    aioclient_mock.post(AUTH, json=load("login.json"))
    aioclient_mock.get(KIDS, status=429, headers={"Retry-After": "120"}, text="slow down")
    with pytest.raises(ProcareRateLimitError) as exc:
        await _client(hass).async_get_kids()
    assert exc.value.retry_after == 120
    assert "slow down" not in str(exc.value)


async def test_rate_limit_without_header(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 429 without a usable Retry-After has retry_after None."""
    aioclient_mock.post(AUTH, json=load("login.json"))
    aioclient_mock.get(KIDS, status=429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    with pytest.raises(ProcareRateLimitError) as exc:
        await _client(hass).async_get_kids()
    assert exc.value.retry_after is None


async def test_errors_hide_host_and_token(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Server errors name the endpoint only."""
    aioclient_mock.post(AUTH, json=load("login.json"))
    aioclient_mock.get(KIDS, status=503, text="test-token-1 internal")
    with pytest.raises(ProcareConnectionError) as exc:
        await _client(hass).async_get_kids()
    message = str(exc.value)
    assert message == "parent/kids/: HTTP 503"
    assert "example" not in message
    assert "test-token" not in message


async def test_requests_are_spaced(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every request waits for REQUEST_GAP after the previous one."""
    monkeypatch.setattr(const, "REQUEST_GAP", 1.0)
    aioclient_mock.post(AUTH, json=load("login.json"))
    aioclient_mock.get(KIDS, json=load("kids.json"))
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    with patch("custom_components.procare_connect.api.asyncio.sleep", fake_sleep):
        client = _client(hass)
        await client.async_get_kids()  # login + kids
        await client.async_get_kids()
    assert len(waits) == 2
    assert all(0.9 < w <= 1.0 for w in waits)
