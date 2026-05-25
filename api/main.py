"""FastAPI service: live endpoints over our DB plus Finnhub REST fallback.

The dashboard talks only to this API, never directly to Postgres or Finnhub.
The ingestor writes ticks/alerts directly. SPEC §7 lists the endpoints; this
module is intentionally thin and uses raw SQL via psycopg (no ORM, per §14).

The /quote and /news endpoints proxy Finnhub's REST API so the dashboard has
something useful to render outside US market hours, when the WebSocket trade
stream is quiet (SPEC §5).
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
FINNHUB_TIMEOUT_S = 5.0
QUOTE_CACHE_TTL_S = 60
NEWS_CACHE_TTL_S = 300
MARKET_STATUS_CACHE_TTL_S = 30
NEWS_WINDOW_DAYS = 7
NEWS_RESPONSE_LIMIT = 10


class HealthResponse(BaseModel):
    status: str


class Tick(BaseModel):
    symbol: str
    ts: datetime
    price: float
    volume: int | None = None


class Alert(BaseModel):
    symbol: str
    ts: datetime
    price: float
    z_score: float
    message: str


class Quote(BaseModel):
    symbol: str
    current: float
    change: float
    percent_change: float
    high: float
    low: float
    open: float
    prev_close: float
    ts: datetime


class NewsItem(BaseModel):
    headline: str
    source: str
    url: str
    summary: str
    ts: datetime
    image: str | None = None


class MarketStatus(BaseModel):
    exchange: str
    is_open: bool
    session: str | None = None
    holiday: str | None = None
    timezone: str
    ts: datetime


class _TTLCache:
    """Tiny per-process TTL cache for Finnhub responses.

    The dashboard polls our API every 10s, and the free Finnhub tier caps at
    60 req/min. Caching /quote for 60s and /company-news for 5 min keeps us
    well under that ceiling even with five symbols.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str, ttl_s: float) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < time.monotonic():
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl_s: float) -> None:
        self._store[key] = (time.monotonic() + ttl_s, value)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")
    finnhub_key = os.environ.get("FINNHUB_API_KEY")
    if not finnhub_key:
        raise RuntimeError("FINNHUB_API_KEY is not set")

    pool = AsyncConnectionPool(dsn, open=False, min_size=1, max_size=4)
    await pool.open()
    http = httpx.AsyncClient(base_url=FINNHUB_BASE_URL, timeout=FINNHUB_TIMEOUT_S)

    app.state.pool = pool
    app.state.http = http
    app.state.finnhub_key = finnhub_key
    app.state.cache = _TTLCache()
    try:
        yield
    finally:
        await http.aclose()
        await pool.close()


app = FastAPI(title="market-data-api", lifespan=lifespan)


async def get_conn(request: Request) -> AsyncIterator[AsyncConnection]:
    pool: AsyncConnectionPool = request.app.state.pool
    async with pool.connection() as conn:
        yield conn


ConnDep = Annotated[AsyncConnection, Depends(get_conn)]


async def _finnhub_get(
    request: Request, path: str, params: dict[str, Any]
) -> dict[str, Any] | list[dict[str, Any]]:
    """One-shot Finnhub call. Adds the token and raises 502 on any error."""
    http: httpx.AsyncClient = request.app.state.http
    params = {**params, "token": request.app.state.finnhub_key}
    try:
        r = await http.get(path, params=params)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Finnhub request failed: {e}") from e


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/prices/{symbol}", response_model=list[Tick])
async def prices(symbol: str, conn: ConnDep, limit: int = 100) -> list[Tick]:
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT symbol, ts, price, volume FROM ticks "
            "WHERE symbol = %s ORDER BY ts DESC LIMIT %s",
            (symbol.upper(), limit),
        )
        rows = await cur.fetchall()
    return [Tick(**row) for row in rows]


@app.get("/alerts", response_model=list[Alert])
async def alerts(conn: ConnDep, limit: int = 20) -> list[Alert]:
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT symbol, ts, price, z_score, message FROM alerts "
            "ORDER BY ts DESC LIMIT %s",
            (limit,),
        )
        rows = await cur.fetchall()
    return [Alert(**row) for row in rows]


@app.get("/quote/{symbol}", response_model=Quote)
async def quote(request: Request, symbol: str) -> Quote:
    sym = symbol.upper()
    cache: _TTLCache = request.app.state.cache
    key = f"quote:{sym}"
    cached = cache.get(key, QUOTE_CACHE_TTL_S)
    if cached is not None:
        return cached

    raw = await _finnhub_get(request, "/quote", {"symbol": sym})
    if not isinstance(raw, dict) or raw.get("t", 0) == 0:
        raise HTTPException(status_code=404, detail=f"No quote for {sym}")

    q = Quote(
        symbol=sym,
        current=raw["c"],
        change=raw["d"] or 0.0,
        percent_change=raw["dp"] or 0.0,
        high=raw["h"],
        low=raw["l"],
        open=raw["o"],
        prev_close=raw["pc"],
        ts=datetime.fromtimestamp(raw["t"], tz=UTC),
    )
    cache.set(key, q, QUOTE_CACHE_TTL_S)
    return q


@app.get("/market-status", response_model=MarketStatus)
async def market_status(request: Request, exchange: str = "US") -> MarketStatus:
    exch = exchange.upper()
    cache: _TTLCache = request.app.state.cache
    key = f"market-status:{exch}"
    cached = cache.get(key, MARKET_STATUS_CACHE_TTL_S)
    if cached is not None:
        return cached

    raw = await _finnhub_get(request, "/stock/market-status", {"exchange": exch})
    if not isinstance(raw, dict):
        raise HTTPException(status_code=502, detail="Unexpected market-status payload")

    status = MarketStatus(
        exchange=raw.get("exchange") or exch,
        is_open=bool(raw.get("isOpen")),
        session=raw.get("session") or None,
        holiday=raw.get("holiday") or None,
        timezone=raw.get("timezone") or "America/New_York",
        ts=datetime.fromtimestamp(raw.get("t") or 0, tz=UTC),
    )
    cache.set(key, status, MARKET_STATUS_CACHE_TTL_S)
    return status


@app.get("/news/{symbol}", response_model=list[NewsItem])
async def news(request: Request, symbol: str) -> list[NewsItem]:
    sym = symbol.upper()
    cache: _TTLCache = request.app.state.cache
    key = f"news:{sym}"
    cached = cache.get(key, NEWS_CACHE_TTL_S)
    if cached is not None:
        return cached

    today = datetime.now(UTC).date()
    raw = await _finnhub_get(
        request,
        "/company-news",
        {
            "symbol": sym,
            "from": (today - timedelta(days=NEWS_WINDOW_DAYS)).isoformat(),
            "to": today.isoformat(),
        },
    )
    if not isinstance(raw, list):
        raise HTTPException(status_code=502, detail="Unexpected news payload")

    # Finnhub returns newest-first, but sort defensively in case that changes.
    items: list[NewsItem] = []
    for entry in raw:
        ts_unix = entry.get("datetime")
        if not ts_unix:
            continue
        items.append(
            NewsItem(
                headline=entry.get("headline") or "",
                source=entry.get("source") or "",
                url=entry.get("url") or "",
                summary=entry.get("summary") or "",
                ts=datetime.fromtimestamp(ts_unix, tz=UTC),
                image=entry.get("image") or None,
            )
        )
    items.sort(key=lambda n: n.ts, reverse=True)
    items = items[:NEWS_RESPONSE_LIMIT]
    cache.set(key, items, NEWS_CACHE_TTL_S)
    return items
