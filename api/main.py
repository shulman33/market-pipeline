"""FastAPI service: three endpoints over the ticks/alerts tables.

The dashboard talks only to this API, never directly to Postgres. The ingestor
writes both tables directly. SPEC §7 spells out the exact endpoints; this
module is intentionally thin and uses raw SQL via psycopg (no ORM, per §14).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel


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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")
    pool = AsyncConnectionPool(dsn, open=False, min_size=1, max_size=4)
    await pool.open()
    app.state.pool = pool
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(title="market-data-api", lifespan=lifespan)


async def get_conn(request: Request) -> AsyncIterator[AsyncConnection]:
    pool: AsyncConnectionPool = request.app.state.pool
    async with pool.connection() as conn:
        yield conn


ConnDep = Annotated[AsyncConnection, Depends(get_conn)]


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
