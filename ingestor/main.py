"""Finnhub WebSocket ingestor.

Persistent WebSocket connection to wss://ws.finnhub.io for a hardcoded list of
symbols. On each trade frame: insert a row into `ticks`, feed the per-symbol
RollingZScore, and insert into `alerts` when an anomaly fires.

The loop must survive Finnhub's ~3-hour forced disconnects (issue #378) and
its occasional "pings but no data" stalls (issue #35), so the design is:

  - websockets.connect with ping_interval=20, ping_timeout=10 (library-level
    keepalive)
  - exponential backoff on disconnect, capped at 60s
  - per-connection watchdog task that closes the socket if no trades arrive
    for 60s during US market hours, forcing the outer loop to reconnect

See SPEC §5 for the full contract.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
import websockets
from psycopg import AsyncConnection
from websockets.exceptions import ConnectionClosed

from ingestor.anomaly import RollingZScore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("ingestor")

SYMBOLS = ["AAPL", "MSFT", "GOOGL", "TSLA", "SPY"]
WS_URL_TEMPLATE = "wss://ws.finnhub.io?token={token}"
SCHEMA_PATH = Path(__file__).parent.parent / "sql" / "schema.sql"

WINDOW_SIZE = 60
Z_THRESHOLD = 2.5

NY_TZ = ZoneInfo("America/New_York")
WATCHDOG_INTERVAL_S = 10
STALE_STREAM_TIMEOUT_S = 60
RECONNECT_INITIAL_BACKOFF_S = 1.0
RECONNECT_MAX_BACKOFF_S = 60.0


@dataclass
class StreamState:
    last_trade_monotonic: float = field(default_factory=time.monotonic)


def is_market_open(now: dt.datetime | None = None) -> bool:
    """US equity regular session: Mon-Fri, 09:30 <= time < 16:00 America/New_York.

    Holidays are intentionally ignored — the watchdog's worst case on a closed
    day is a single spurious reconnect, which is cheap.
    """
    now = now or dt.datetime.now(NY_TZ)
    if now.weekday() >= 5:
        return False
    open_t = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_t <= now < close_t


def wait_for_postgres(dsn: str, timeout_s: float = 30.0) -> None:
    """Block until Postgres accepts a connection, or raise after `timeout_s`.

    Used at startup because docker-compose `depends_on` only checks process
    liveness, not readiness, on older Compose versions.
    """
    deadline = time.monotonic() + timeout_s
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=2) as conn:
                conn.execute("SELECT 1")
            return
        except psycopg.OperationalError as e:
            last_err = e
            time.sleep(1.0)
    raise RuntimeError(f"Postgres not reachable within {timeout_s}s: {last_err}")


def apply_schema_if_missing(dsn: str) -> None:
    """Idempotent schema apply.

    The canonical schema lives in sql/schema.sql with bare CREATE TABLE
    statements (so the Postgres container's init-script mount can apply it
    cleanly on a fresh volume). To make the ingestor safe on an already-
    initialised volume, we skip the apply when `ticks` already exists.
    """
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.ticks')")
            row = cur.fetchone()
            if row is not None and row[0] is not None:
                log.info("schema already present, skipping apply")
                return
        log.info("applying sql/schema.sql")
        conn.execute(SCHEMA_PATH.read_text())
        conn.commit()


async def _handle_trade(
    conn: AsyncConnection,
    detectors: dict[str, RollingZScore],
    trade: dict,
) -> None:
    symbol = trade.get("s")
    price = trade.get("p")
    t_ms = trade.get("t")
    if not symbol or price is None or t_ms is None:
        return
    volume = trade.get("v")
    ts = dt.datetime.fromtimestamp(t_ms / 1000.0, tz=dt.UTC)

    await conn.execute(
        "INSERT INTO ticks (symbol, ts, price, volume) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (symbol, ts) DO NOTHING",
        (symbol, ts, price, volume),
    )

    detector = detectors.get(symbol)
    if detector is None:
        return
    result = detector.update(float(price))
    if result.is_anomaly and result.z_score is not None:
        message = f"{symbol} spike: z={result.z_score:+.2f} @ {price}"
        await conn.execute(
            "INSERT INTO alerts (symbol, ts, price, z_score, message) "
            "VALUES (%s, %s, %s, %s, %s)",
            (symbol, ts, price, result.z_score, message),
        )
        log.warning("alert: %s", message)


async def _watchdog(ws, state: StreamState) -> None:
    while True:
        await asyncio.sleep(WATCHDOG_INTERVAL_S)
        idle = time.monotonic() - state.last_trade_monotonic
        if is_market_open() and idle > STALE_STREAM_TIMEOUT_S:
            log.warning(
                "no trades for %.0fs during market hours, forcing reconnect", idle
            )
            await ws.close()
            return


async def _run_connection(
    conn: AsyncConnection,
    detectors: dict[str, RollingZScore],
    token: str,
) -> None:
    url = WS_URL_TEMPLATE.format(token=token)
    async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
        for symbol in SYMBOLS:
            await ws.send(json.dumps({"type": "subscribe", "symbol": symbol}))
        log.info("subscribed to %s", SYMBOLS)

        state = StreamState()
        watchdog_task = asyncio.create_task(_watchdog(ws, state))
        try:
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") != "trade":
                    continue
                state.last_trade_monotonic = time.monotonic()
                for trade in msg.get("data", []):
                    await _handle_trade(conn, detectors, trade)
        finally:
            watchdog_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await watchdog_task


async def run() -> None:
    token = os.environ.get("FINNHUB_API_KEY")
    if not token:
        raise SystemExit("FINNHUB_API_KEY is not set")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is not set")

    wait_for_postgres(dsn)
    apply_schema_if_missing(dsn)

    detectors = {s: RollingZScore(WINDOW_SIZE, Z_THRESHOLD) for s in SYMBOLS}
    backoff = RECONNECT_INITIAL_BACKOFF_S

    async with await AsyncConnection.connect(dsn, autocommit=True) as conn:
        while True:
            try:
                await _run_connection(conn, detectors, token)
                # Clean close: log and reconnect immediately.
                log.info("websocket closed cleanly, reconnecting")
                backoff = RECONNECT_INITIAL_BACKOFF_S
            except (TimeoutError, ConnectionClosed, OSError) as e:
                log.warning("websocket disconnected: %s; backoff=%.1fs", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RECONNECT_MAX_BACKOFF_S)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
