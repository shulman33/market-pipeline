"""End-to-end test for the Java matching-engine service against a real Postgres.

Spins up Postgres 16 plus the locally-built matching-engine image
(goldman-porfolio-matching-engine:latest) on a shared docker network. Drives
the engine through its HTTP API and asserts persisted state in Postgres. No
mocks.

Prerequisite: the matching-engine image must be built before this test runs.
In CI, run `docker compose build matching-engine` first; the existing api/test
file documents the same image-prereq pattern.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import psycopg
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network
from testcontainers.postgres import PostgresContainer

SCHEMA_PATH = Path(__file__).parent.parent / "sql" / "schema.sql"
ENGINE_IMAGE = "goldman-porfolio-matching-engine:latest"
TEST_SYMBOL = "SYNTH1"
READY_TIMEOUT_S = 30.0


@pytest.fixture(scope="module")
def shared_network() -> Iterator[Network]:
    with Network() as net:
        yield net


@pytest.fixture(scope="module")
def postgres(shared_network: Network) -> Iterator[PostgresContainer]:
    container = (
        PostgresContainer("postgres:16-alpine")
        .with_network(shared_network)
        .with_network_aliases("postgres")
    )
    with container as pg:
        host_url = pg.get_connection_url().replace("postgresql+psycopg2", "postgresql")
        with psycopg.connect(host_url) as conn:
            conn.execute(SCHEMA_PATH.read_text())
            conn.commit()
        yield pg


@pytest.fixture(scope="module")
def postgres_host_url(postgres: PostgresContainer) -> str:
    return postgres.get_connection_url().replace("postgresql+psycopg2", "postgresql")


@pytest.fixture(scope="module")
def engine_url(postgres: PostgresContainer, shared_network: Network) -> Iterator[str]:
    db_url_in_net = (
        f"postgresql://{postgres.username}:{postgres.password}"
        f"@postgres:5432/{postgres.dbname}"
    )
    engine = (
        DockerContainer(ENGINE_IMAGE)
        .with_network(shared_network)
        .with_env("DATABASE_URL", db_url_in_net)
        .with_env("HTTP_PORT", "8080")
        .with_env("ME_SYMBOLS", TEST_SYMBOL)
        .with_env("ME_SEED", "12345")
        .with_exposed_ports(8080)
    )
    engine.start()
    try:
        host = engine.get_container_host_ip()
        port = engine.get_exposed_port(8080)
        url = f"http://{host}:{port}"
        deadline = time.monotonic() + READY_TIMEOUT_S
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            try:
                httpx.get(f"{url}/health", timeout=1.0).raise_for_status()
                break
            except (httpx.HTTPError, OSError) as e:
                last_err = e
                time.sleep(0.5)
        else:
            raise RuntimeError(f"matching-engine did not become ready: {last_err}")
        yield url
    finally:
        engine.stop()


@pytest.fixture(scope="module")
def client(engine_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=engine_url, timeout=5.0) as c:
        yield c


def _row_count(url: str, table: str) -> int:
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        row = cur.fetchone()
        assert row is not None
        return int(row[0])


def test_health(client: httpx.Client) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_resting_limit_appears_in_book_and_orders_table(
    client: httpx.Client, postgres_host_url: str
) -> None:
    # The generator is running in the background; we wait for the synthetic
    # flow to have populated the book at least once.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        top = client.get(f"/book/{TEST_SYMBOL}/top").json()
        if top.get("bestBid") is not None or top.get("bestAsk") is not None:
            break
        time.sleep(0.2)
    assert top.get("bestBid") is not None or top.get("bestAsk") is not None

    assert _row_count(postgres_host_url, "me_orders") > 0


def test_crossing_limit_produces_a_trade_and_db_row(
    client: httpx.Client, postgres_host_url: str
) -> None:
    # Place a far-from-mid resting sell, then a market buy that consumes it.
    sell = client.post(
        "/orders",
        json={
            "symbol": TEST_SYMBOL,
            "side": "SELL",
            "type": "LIMIT",
            "price": "500.00",
            "quantity": 5,
        },
    ).json()
    assert sell["resting"] is True

    before = _row_count(postgres_host_url, "me_trades")

    buy = client.post(
        "/orders",
        json={
            "symbol": TEST_SYMBOL,
            "side": "BUY",
            "type": "LIMIT",
            "price": "500.00",
            "quantity": 5,
        },
    ).json()

    assert buy["fullyFilled"] is True
    assert len(buy["trades"]) == 1
    fill = buy["trades"][0]
    assert fill["makerOrderId"] == sell["orderId"]
    assert fill["takerOrderId"] == buy["orderId"]
    assert float(fill["price"]) == 500.00
    assert fill["quantity"] == 5

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        after = _row_count(postgres_host_url, "me_trades")
        if after > before:
            break
        time.sleep(0.1)
    assert after > before


def test_cancel_removes_resting_order(client: httpx.Client) -> None:
    r = client.post(
        "/orders",
        json={
            "symbol": TEST_SYMBOL,
            "side": "BUY",
            "type": "LIMIT",
            "price": "1.00",
            "quantity": 1,
        },
    ).json()
    order_id = r["orderId"]
    assert r["resting"] is True

    cancel = client.delete(f"/orders/{order_id}").json()
    assert cancel["cancelled"] is True
    assert cancel["orderId"] == order_id

    # Second cancel should report not-found.
    second = client.delete(f"/orders/{order_id}")
    assert second.status_code == 404


def test_snapshot_writer_populates_book_snapshots(
    client: httpx.Client, postgres_host_url: str
) -> None:
    # The snapshot writer fires once per second; wait for at least one tick.
    deadline = time.monotonic() + 4.0
    count = 0
    while time.monotonic() < deadline:
        count = _row_count(postgres_host_url, "me_book_snapshots")
        if count > 0:
            break
        time.sleep(0.5)
    assert count > 0


def test_unknown_symbol_returns_404(client: httpx.Client) -> None:
    r = client.get("/book/NOPE/top")
    assert r.status_code == 404


def test_limit_without_price_rejected(client: httpx.Client) -> None:
    r = client.post(
        "/orders",
        json={"symbol": TEST_SYMBOL, "side": "BUY", "type": "LIMIT", "quantity": 1},
    )
    assert r.status_code == 400
