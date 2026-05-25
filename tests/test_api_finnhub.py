"""Tests for the /quote and /news endpoints (Finnhub REST fallback).

The dashboard ↔ API path is real (ASGITransport over httpx); only the
outbound api → Finnhub.io HTTP layer is mocked, which matches the project's
"no mocks for our own stack" rule (SPEC §7, CLAUDE.md). pytest-httpx
intercepts httpx calls globally, so we mark our test host (`test`) as
non-mocked.
"""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from pytest_httpx import HTTPXMock
from testcontainers.postgres import PostgresContainer

from tests.conftest import apply_schema

NEWS_URL_PATTERN = re.compile(
    r"^https://finnhub\.io/api/v1/company-news\?.*symbol=AAPL.*token=test-key.*$"
)


@pytest.fixture(scope="module")
def postgres_url() -> AsyncIterator[str]:
    with PostgresContainer("postgres:16-alpine") as pg:
        yield apply_schema(pg)


@pytest_asyncio.fixture(scope="module")
async def client(postgres_url: str) -> AsyncIterator[httpx.AsyncClient]:
    os.environ["DATABASE_URL"] = postgres_url
    os.environ.setdefault("FINNHUB_API_KEY", "test-key")
    from api.main import app

    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    """Clear the API's in-process Finnhub TTL cache between tests."""
    from api.main import app

    if hasattr(app.state, "cache"):
        app.state.cache._store.clear()


@pytest.fixture
def non_mocked_hosts() -> list[str]:
    """Let calls to our ASGI test client pass through pytest-httpx untouched."""
    return ["test"]


def _quote_payload(price: float = 187.42) -> dict:
    return {
        "c": price,
        "d": 1.25,
        "dp": 0.67,
        "h": 188.10,
        "l": 185.50,
        "o": 186.00,
        "pc": 186.17,
        "t": 1_700_000_000,
    }


def _news_payload() -> list[dict]:
    return [
        {
            "category": "company news",
            "datetime": 1_700_001_000,
            "headline": "AAPL beats earnings",
            "id": 1,
            "image": "https://img/1.jpg",
            "related": "AAPL",
            "source": "Reuters",
            "summary": "Apple reported a strong quarter.",
            "url": "https://example.com/aapl-earnings",
        },
        {
            "category": "company news",
            "datetime": 1_700_000_500,
            "headline": "Older AAPL news",
            "id": 2,
            "image": "",
            "related": "AAPL",
            "source": "Bloomberg",
            "summary": "",
            "url": "https://example.com/older",
        },
    ]


async def test_quote_success(client: httpx.AsyncClient, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://finnhub.io/api/v1/quote?symbol=AAPL&token=test-key",
        json=_quote_payload(),
    )
    r = await client.get("/quote/AAPL")
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "AAPL"
    assert body["current"] == pytest.approx(187.42)
    assert body["percent_change"] == pytest.approx(0.67)
    assert body["prev_close"] == pytest.approx(186.17)
    assert body["ts"].startswith("2023-")  # 1.7e9 epoch is Nov 2023


async def test_quote_lowercase_symbol_is_uppercased(
    client: httpx.AsyncClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        url="https://finnhub.io/api/v1/quote?symbol=AAPL&token=test-key",
        json=_quote_payload(),
    )
    r = await client.get("/quote/aapl")
    assert r.status_code == 200
    assert r.json()["symbol"] == "AAPL"


async def test_quote_unknown_symbol_404(
    client: httpx.AsyncClient, httpx_mock: HTTPXMock
) -> None:
    # Finnhub returns zeros and t=0 for unknown symbols rather than a 404.
    httpx_mock.add_response(
        url="https://finnhub.io/api/v1/quote?symbol=NOPE&token=test-key",
        json={"c": 0, "d": None, "dp": None, "h": 0, "l": 0, "o": 0, "pc": 0, "t": 0},
    )
    r = await client.get("/quote/NOPE")
    assert r.status_code == 404


async def test_quote_finnhub_error_502(
    client: httpx.AsyncClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        url="https://finnhub.io/api/v1/quote?symbol=AAPL&token=test-key",
        status_code=500,
    )
    r = await client.get("/quote/AAPL")
    assert r.status_code == 502


async def test_quote_cache_hit_within_ttl(
    client: httpx.AsyncClient, httpx_mock: HTTPXMock
) -> None:
    # Register exactly one mock response. The second call must hit the
    # in-process TTL cache; otherwise pytest-httpx will raise on the
    # un-mocked second outbound request.
    httpx_mock.add_response(
        url="https://finnhub.io/api/v1/quote?symbol=MSFT&token=test-key",
        json=_quote_payload(price=420.50),
        is_reusable=False,
    )
    r1 = await client.get("/quote/MSFT")
    r2 = await client.get("/quote/MSFT")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()
    # Exactly one outbound Finnhub request was made.
    assert len(httpx_mock.get_requests()) == 1


async def test_news_success_sorted_newest_first(
    client: httpx.AsyncClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(url=NEWS_URL_PATTERN, json=_news_payload())
    r = await client.get("/news/AAPL")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    assert items[0]["headline"] == "AAPL beats earnings"
    assert items[1]["headline"] == "Older AAPL news"
    assert items[0]["image"] == "https://img/1.jpg"
    # Empty image string normalizes to None.
    assert items[1]["image"] is None


async def test_news_finnhub_error_502(
    client: httpx.AsyncClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(url=NEWS_URL_PATTERN, status_code=500)
    r = await client.get("/news/AAPL")
    assert r.status_code == 502


async def test_market_status_open(
    client: httpx.AsyncClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        url="https://finnhub.io/api/v1/stock/market-status?exchange=US&token=test-key",
        json={
            "exchange": "US",
            "holiday": None,
            "isOpen": True,
            "session": "regular",
            "timezone": "America/New_York",
            "t": 1_700_000_000,
        },
    )
    r = await client.get("/market-status")
    assert r.status_code == 200
    body = r.json()
    assert body["is_open"] is True
    assert body["session"] == "regular"
    assert body["holiday"] is None
    assert body["exchange"] == "US"


async def test_market_status_closed_pre_market(
    client: httpx.AsyncClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        url="https://finnhub.io/api/v1/stock/market-status?exchange=US&token=test-key",
        json={
            "exchange": "US",
            "holiday": None,
            "isOpen": False,
            "session": "pre-market",
            "timezone": "America/New_York",
            "t": 1_697_018_041,
        },
    )
    r = await client.get("/market-status")
    assert r.status_code == 200
    body = r.json()
    assert body["is_open"] is False
    assert body["session"] == "pre-market"


async def test_market_status_caches(
    client: httpx.AsyncClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        url="https://finnhub.io/api/v1/stock/market-status?exchange=US&token=test-key",
        json={
            "exchange": "US",
            "holiday": None,
            "isOpen": True,
            "session": "regular",
            "timezone": "America/New_York",
            "t": 1_700_000_000,
        },
        is_reusable=False,
    )
    r1 = await client.get("/market-status")
    r2 = await client.get("/market-status")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()
    assert len(httpx_mock.get_requests()) == 1
