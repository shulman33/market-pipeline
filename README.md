# Real-Time Market Data Pipeline + Limit-Order-Book Matching Engine

A four-service stack that ingests real-time US-equity trades over Finnhub's
WebSocket, runs a per-symbol rolling z-score anomaly detector, simulates a
price-time-priority matching engine with synthetic order flow, and renders
everything live on a Streamlit dashboard.

**Live demo:** http://3.232.132.2:8501

> Note: the Finnhub-driven view shows market data only during US trading hours
> (09:30 to 16:00 New York time, weekdays). The Matching Engine view is always
> live because its order flow is generated internally.

## What this demonstrates

Mapped to the keywords on the Goldman Sachs Software Engineer Analyst JD:

| JD keyword | Where it lives |
|---|---|
| Java | `matching-engine/` (Java 17 + Maven + Javalin), 25 JUnit tests |
| Python | `ingestor/`, `api/`, `dashboard/`, 21 pytest tests |
| SQL, relational DB | `sql/schema.sql`, Postgres 16, raw `psycopg` (no ORM) |
| Data structures and algorithms | Rolling z-score with O(1) updates; price-time-priority order book with `TreeMap` price levels and a `HashMap` for O(1) cancel |
| Microservices | Four services (ingestor, api, matching-engine, dashboard) over HTTP and Postgres |
| Low-latency | Outbound WebSocket to Finnhub for sub-second ticks; 50 ms synthetic generator cadence; client-side prepared-statement caching in the Java service |
| Docker | One Dockerfile per service, `docker-compose.yml` wires the stack |
| AWS | Deployed on AWS Lightsail (Ubuntu 24.04 instance, 2 GB) running `docker compose` |
| CI/CD | GitHub Actions on push and PR (lint + pytest + JUnit + compose build) |
| Automated tests | 25/25 JUnit, 21/21 pytest including 8 real end-to-end API tests against a testcontainers-managed Postgres (no mocks) |
| Financial markets | Anomaly alerts on real-time prices; a synthetic exchange that fills orders by price-time priority |

## Architecture

```
                                       ┌──────────────────┐
                                       │  wss://ws.       │
                                       │   finnhub.io     │
                                       └────────┬─────────┘
                                                │ trade ticks
                                                ▼
  ┌────────────┐    writes    ┌──────────┐    reads    ┌────────────┐
  │  ingestor  │ ───────────▶ │ postgres │ ◀────────── │    api     │
  │  (Python)  │              │          │             │ (FastAPI)  │
  └────────────┘              └──────────┘             └─────┬──────┘
                                  ▲                          │
                                  │ writes                   │ HTTP
                                  │                          ▼
                          ┌───────┴────────┐         ┌──────────────┐
                          │ matching-engine│ ◀──────▶│  dashboard   │
                          │     (Java)     │  HTTP   │ (Streamlit)  │
                          └────────────────┘         └──────────────┘
                                  ▲
                                  │ 50 ms ticks
                          ┌───────┴────────┐
                          │   synthetic    │
                          │   generator    │
                          └────────────────┘
```

- **ingestor (Python).** Persistent WebSocket to `wss://ws.finnhub.io` for five
  symbols (AAPL, MSFT, GOOGL, TSLA, SPY). On each trade frame: insert into
  `ticks`, feed the per-symbol `RollingZScore`, insert into `alerts` if the
  z-score exceeds the threshold. Auto-reconnect with exponential backoff, plus
  a stale-stream watchdog that forces a reconnect if no trades arrive for 60
  seconds during market hours.
- **api (FastAPI).** Three read endpoints: `/health`, `/prices/{symbol}`,
  `/alerts`. Raw SQL through `psycopg` with an `AsyncConnectionPool`. The
  dashboard never touches the database directly.
- **matching-engine (Java).** Standalone limit-order-book service. Maintains
  per-symbol order books and a synthetic-flow generator (70 percent limit
  orders, 20 percent market, 10 percent cancels at 50 ms cadence). Exposes
  HTTP endpoints for top-of-book, depth ladder, and recent trades. Persists
  orders, trades, and per-second book snapshots to its own `me_*` tables.
- **dashboard (Streamlit + Plotly).** Multi-page app. Page one is the Finnhub
  view: live price chart for the selected symbol with red dots overlaid where
  anomaly alerts fired. Page two is the Matching Engine view: top-of-book
  spread, depth ladder, recent trades. Both pages read exclusively from
  HTTP APIs.

## Quickstart (local)

Requires Docker and a free Finnhub API key (no credit card needed).

```bash
git clone https://github.com/shulman33/goldman-portfolio.git
cd goldman-portfolio
cp .env.example .env
# Edit .env: set FINNHUB_API_KEY to your free key from https://finnhub.io
docker compose up -d
```

Then open:

- Dashboard: http://localhost:8501
- API: http://localhost:8000/health
- Matching engine: http://localhost:8080/health

## Tests

```bash
# Python: lint + unit tests + real E2E tests against a testcontainers Postgres
.venv/bin/ruff check .
.venv/bin/python -m pytest -v

# Java: limit-order-book DS&A coverage
cd matching-engine && mvn test
```

The Python end-to-end suite (`tests/test_api.py`,
`tests/test_matching_engine.py`) deliberately uses no mocks: it spins a real
Postgres 16 container via `testcontainers-python`, applies `sql/schema.sql`,
inserts known rows, and exercises the same `psycopg` driver and ASGI stack
that runs in production. If a test passes there, the production code path
works.

## Design notes

### Rolling z-score in O(1) per update

`ingestor/anomaly.py` is the deliberate DS&A showcase. The detector watches
each symbol's log-returns over a sliding window of 60 ticks. Naively
recomputing mean and standard deviation each tick would be O(window). Instead
the class maintains:

- a `collections.deque(maxlen=60)` of recent log-returns,
- a running `sum`, and
- a running `sum_of_squares`.

Each new return updates both totals by two scalar operations and (when the
window is full) subtracts the soon-to-be-evicted value first, so the totals
stay in sync with the deque in O(1). Variance is `sum_sq / n - mean * mean`,
and the z-score is `(return - mean) / sqrt(variance)`. An alert fires when
`|z| > 2.5` and the window is warm. No NumPy, no SciPy, no library
abstractions: the running-sums pattern is the entire point.

### Price-time-priority order book with O(log n) submit and O(1) cancel

`matching-engine/.../OrderBook.java` keeps two sides:

- `TreeMap<BigDecimal, PriceLevel>` for bids (reverse-ordered: best bid first)
  and asks (natural order: best ask first). Each price level holds a doubly-
  linked FIFO of orders.
- `HashMap<Long, Order>` mapping order id to order, so a cancel is an O(1)
  lookup, an O(1) unlink from the FIFO, and an O(log n) tree-remove only if
  the level becomes empty.

Matching sweeps the opposite tree's first entry, then walks its FIFO. Limit
orders that do not fully fill rest at their price. Market orders never rest.
Every public method on `OrderBook` is `synchronized`: matching has to be
linearizable, and one coarse lock is the right tool given the engine is
single-threaded per book on the producer side.

### Why Finnhub WebSocket, not `yfinance` REST polling

`yfinance` is an unofficial Yahoo Finance scraper with no SLA. It has broken
multiple times in 2026 and is aggressively rate-limited. A portfolio URL that
goes empty because Yahoo blocked the host IP is the wrong impression.

Finnhub is officially supported and gives real-time US equity trades on the
free tier over a WebSocket that the vendor explicitly recommends over REST
polling. The library handles ping/pong; we handle reconnect with backoff and
a watchdog for the documented "pings only, no data" failure mode.

### Atomicity of tick and alert writes

`ingestor/main.py` writes a tick and (when applicable) its derived alert
inside one `conn.transaction()`. The connection runs in autocommit mode, so
`conn.transaction()` issues a real `BEGIN`/`COMMIT` rather than a savepoint.
This guarantees a price spike on the chart cannot exist without its alert
marker, even if the ingestor crashes mid-trade.

### Synthetic generator, not Finnhub-driven, for the matching engine

The matching engine is a standalone subsystem with its own tables (`me_*`),
its own HTTP API, and its own simulation driver. Reasons not to bridge it to
the Finnhub tick stream: (a) outside market hours nothing flows and the
matching-engine demo dies with it, (b) the synthetic generator is
deterministic with a seed, which gives reproducible book state for tests and
screenshots, and (c) keeping the two subsystems decoupled preserves the
option to lift either one out into its own repo.

## Repo layout

```
.
├── README.md
├── SPEC.md                       # authoritative one-day build plan
├── job-description.md            # the JD this project maps to
├── docker-compose.yml            # four services + Postgres
├── sql/schema.sql                # five tables, two subsystems
├── ingestor/                     # Finnhub WebSocket + rolling z-score
│   ├── main.py
│   └── anomaly.py
├── api/main.py                   # FastAPI
├── dashboard/
│   ├── app.py                    # page 1: Finnhub view
│   ├── pages/1_matching_engine.py# page 2: matching-engine view
│   └── _shared.py
├── matching-engine/              # Java limit-order-book service
│   ├── pom.xml
│   └── src/main/java/com/portfolio/matching/...
├── tests/
│   ├── test_anomaly.py           # 6 unit tests (no Docker)
│   ├── test_api.py               # 8 real E2E tests (testcontainers)
│   └── test_matching_engine.py   # 7 real E2E tests against the Java image
└── session-summaries/            # detailed build-session writeups
```

## Deployment

Deployed on AWS Lightsail. The original plan in `SPEC.md` §11 used a Lightsail
Container Service for the application containers plus a separate Lightsail
Instance for Postgres. Adding the Java matching engine made that topology
tight on RAM, so this build runs the entire `docker-compose.yml` on a single
Lightsail Instance (Ubuntu 24.04, 2 GB, first 90 days free). The same image
set, the same compose file, the same `.env` shape: no production-only code
paths.

The instance was provisioned by hand: install Docker, clone this repo, write
the `.env` file, `docker compose up -d`. A CI workflow in
`.github/workflows/ci.yml` runs lint, pytest, JUnit, and `docker compose
build` on every push.

## Status

- 25/25 JUnit pass (`OrderBookTest`, `PriceLevelTest`, `SyntheticOrderGeneratorTest`)
- 21/21 pytest pass (6 anomaly unit, 8 API E2E, 7 matching-engine E2E)
- `ruff check .` clean
- Live on the URL at the top of this README

## License

Personal portfolio project; no license granted for reuse.

Market data: [Finnhub](https://finnhub.io).
