"""End-to-end API test against a real Postgres (no mocks).

Per SPEC §7, this test exercises the full production code path: real Postgres
running in a container, the same `psycopg` driver the app uses, the actual
ASGI app under `httpx.AsyncClient`. Requires a running Docker daemon
(testcontainers starts a Postgres 16 container for the module).

If something doesn't work here, it doesn't work in production.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import psycopg
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from testcontainers.postgres import PostgresContainer

SCHEMA_PATH = Path(__file__).parent.parent / "sql" / "schema.sql"


@pytest.fixture(scope="module")
def postgres_url() -> AsyncIterator[str]:
    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url().replace("postgresql+psycopg2", "postgresql")
        with psycopg.connect(url) as conn:
            conn.execute(SCHEMA_PATH.read_text())
            conn.commit()
        yield url


@pytest_asyncio.fixture(scope="module")
async def client(postgres_url: str) -> AsyncIterator[httpx.AsyncClient]:
    os.environ["DATABASE_URL"] = postgres_url
    # Import after env is set so the lifespan reads the test DSN.
    from api.main import app

    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(autouse=True)
async def reset_db(postgres_url: str) -> None:
    async with await psycopg.AsyncConnection.connect(postgres_url) as conn:
        await conn.execute("TRUNCATE ticks, alerts RESTART IDENTITY")
        await conn.commit()


async def _insert_tick(
    url: str, symbol: str, ts: dt.datetime, price: float, volume: int | None = None
) -> None:
    async with await psycopg.AsyncConnection.connect(url) as conn:
        await conn.execute(
            "INSERT INTO ticks (symbol, ts, price, volume) VALUES (%s, %s, %s, %s)",
            (symbol, ts, price, volume),
        )
        await conn.commit()


async def _insert_alert(
    url: str, symbol: str, ts: dt.datetime, price: float, z_score: float, message: str
) -> None:
    async with await psycopg.AsyncConnection.connect(url) as conn:
        await conn.execute(
            "INSERT INTO alerts (symbol, ts, price, z_score, message) "
            "VALUES (%s, %s, %s, %s, %s)",
            (symbol, ts, price, z_score, message),
        )
        await conn.commit()


async def test_health_returns_ok(client: httpx.AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_prices_returns_newest_first(
    postgres_url: str, client: httpx.AsyncClient
) -> None:
    now = dt.datetime.now(dt.UTC).replace(microsecond=0)
    await _insert_tick(postgres_url, "AAPL", now - dt.timedelta(seconds=2), 100.00)
    await _insert_tick(postgres_url, "AAPL", now - dt.timedelta(seconds=1), 101.00)
    await _insert_tick(postgres_url, "AAPL", now, 102.00, volume=500)
    # A row for a different symbol must not appear in the AAPL response.
    await _insert_tick(postgres_url, "MSFT", now, 300.00)

    r = await client.get("/prices/AAPL")
    assert r.status_code == 200
    data = r.json()
    assert [row["price"] for row in data] == [102.00, 101.00, 100.00]
    assert all(row["symbol"] == "AAPL" for row in data)
    assert data[0]["volume"] == 500


async def test_prices_lowercase_symbol_is_uppercased(
    postgres_url: str, client: httpx.AsyncClient
) -> None:
    now = dt.datetime.now(dt.UTC).replace(microsecond=0)
    await _insert_tick(postgres_url, "AAPL", now, 150.00)
    r = await client.get("/prices/aapl")
    assert r.status_code == 200
    assert len(r.json()) == 1


async def test_prices_limit_honored(
    postgres_url: str, client: httpx.AsyncClient
) -> None:
    now = dt.datetime.now(dt.UTC).replace(microsecond=0)
    for i in range(5):
        await _insert_tick(postgres_url, "AAPL", now - dt.timedelta(seconds=i), 100.0 + i)
    r = await client.get("/prices/AAPL?limit=2")
    assert r.status_code == 200
    assert len(r.json()) == 2


async def test_prices_unknown_symbol_returns_empty(client: httpx.AsyncClient) -> None:
    r = await client.get("/prices/NOPE")
    assert r.status_code == 200
    assert r.json() == []


async def test_prices_invalid_limit_rejected(client: httpx.AsyncClient) -> None:
    r = await client.get("/prices/AAPL?limit=0")
    assert r.status_code == 400
    r = await client.get("/prices/AAPL?limit=99999")
    assert r.status_code == 400


async def test_alerts_returns_newest_first(
    postgres_url: str, client: httpx.AsyncClient
) -> None:
    now = dt.datetime.now(dt.UTC).replace(microsecond=0)
    await _insert_alert(postgres_url, "AAPL", now - dt.timedelta(seconds=1), 100.0, 3.5, "old")
    await _insert_alert(postgres_url, "MSFT", now, 200.0, 4.0, "new")
    r = await client.get("/alerts")
    assert r.status_code == 200
    data = r.json()
    assert [row["symbol"] for row in data] == ["MSFT", "AAPL"]
    assert data[0]["message"] == "new"


async def test_alerts_limit_honored(
    postgres_url: str, client: httpx.AsyncClient
) -> None:
    now = dt.datetime.now(dt.UTC).replace(microsecond=0)
    for i in range(5):
        await _insert_alert(
            postgres_url, "AAPL", now - dt.timedelta(seconds=i), 100.0 + i, 3.0, f"a{i}"
        )
    r = await client.get("/alerts?limit=2")
    assert r.status_code == 200
    assert len(r.json()) == 2
