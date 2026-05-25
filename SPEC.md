# SPEC: Real-Time Market Data Pipeline

A small system that ingests real-time market data for a handful of tickers via Finnhub, stores it in Postgres, exposes a FastAPI service, and renders a live Streamlit dashboard with price charts and anomaly alerts. Deployed publicly on AWS Lightsail so a Goldman recruiter can click a live URL from the README.

Built as a portfolio piece for a Goldman Sachs Software Engineer Analyst application. Every component maps directly to a JD keyword. **Optimize for clarity and shippability in one day, not for production scale.**

---

## Goals

Hit these JD keywords through working code:

- Python, SQL / relational DB (Postgres)
- Microservices (3 small services, talk over HTTP + DB)
- Docker, docker-compose
- **AWS** (deployed on Lightsail Container Service — see §11)
- Git, CI/CD (GitHub Actions), automated tests (pytest) — including a real end-to-end API test
- Data structures & algorithms (rolling-window anomaly detector — see §6)
- Financial markets / "data into action" (alerts on anomalies)

Non-goals: auth, multi-user, K8s, message queues, ORMs, microsecond latency, a real trading strategy.

---

## 1. Architecture

Three services + Postgres, wired with docker-compose:

```
  ┌────────────┐    writes    ┌──────────┐    reads    ┌────────────┐
  │  ingestor  │ ───────────▶ │ postgres │ ◀────────── │    api     │
  │  (Python)  │              │          │             │ (FastAPI)  │
  └────────────┘              └──────────┘             └─────┬──────┘
                                                             │ HTTP
                                                             ▼
                                                      ┌─────────────┐
                                                      │  dashboard  │
                                                      │ (Streamlit) │
                                                      └─────────────┘
```

- **ingestor** — polls `yfinance` every 30s for ~5 symbols, writes ticks, runs anomaly detection, writes alerts.
- **api** — FastAPI; serves latest prices, price history, recent alerts.
- **dashboard** — Streamlit; auto-refreshes, shows live charts + an alerts feed.

---

## 2. Tech stack

| Concern | Choice |
|---|---|
| Language | Python 3.14 |
| Market data | Finnhub **WebSocket** trade stream — `wss://ws.finnhub.io` (see §5) |
| WS client | `websockets` library (async, native asyncio) |
| DB | Postgres 16 |
| DB driver | `psycopg[binary]` — raw SQL, no ORM |
| API | FastAPI + uvicorn |
| Dashboard | Streamlit + Plotly |
| Tests | pytest |
| Lint/format | ruff |
| Container | Docker, docker-compose |
| CI | GitHub Actions |
| Deploy | AWS Lightsail Container Service (see §11) |

### Why Finnhub over yfinance

`yfinance` was the original pick but was rejected on research:
- It's an unofficial Yahoo Finance scraper with no SLA — it broke repeatedly in 2025 and is rate-limited aggressively.
- Recruiter risk: if Goldman clicks your live URL a week from now and the dashboard is empty because Yahoo blocked the IP, that's the wrong impression.

Finnhub is officially supported, gives real-time US equity trade data on the free tier, and offers a WebSocket feed Finnhub themselves recommend over REST polling. Requires a free API key, no credit card. Stored as `FINNHUB_API_KEY` env var.

### Why WebSocket over REST polling

The official Finnhub docs explicitly state: *"Constant polling is not recommended. Use websocket if you need real-time updates."* We respect that guidance because:

1. **Vendor alignment.** A portfolio piece that ignores the vendor's own documented recommendation invites the interview question *"why didn't you use the WebSocket?"* — that's a question we don't want to answer with "I didn't know."
2. **Honest "low-latency" keyword.** The JD lists low-latency applications as a design objective. Sub-second WebSocket trade ticks earn that keyword; 30-second polling does not.
3. **Cleaner off-hours behaviour.** WebSocket simply delivers no trade events outside market hours, so the REST-era `t == 0` guard becomes a non-issue.
4. **Stronger interview narrative.** "Subscribes to a real-time trade-tick stream" reads measurably better than "polls a REST endpoint" — same effort tier, better story.

Free tier covers our usage with significant headroom: **50-symbol cap** (we use 5), unmetered message rate after the subscribe handshake, real-time IEX-sourced US equity trades.

### What we are *not* doing with WebSocket

The FastAPI WebSocket feature (server-side endpoints with `@app.websocket(...)`) is **not used**. The dashboard continues to poll the REST API at 10s intervals — that traffic is internal (no rate limits, no latency cost) and Streamlit consumes REST naturally but does not consume WebSocket without hand-rolled integration. Adding a WebSocket server in our API for a single-user portfolio demo doesn't pay off within a one-day build. The only WebSocket in the system is the outbound connection from the ingestor to Finnhub.

---

## 3. Repo layout

```
.
├── README.md              # polished, with screenshot/GIF — see §9
├── SPEC.md                # this file
├── docker-compose.yml
├── .github/workflows/ci.yml
├── pyproject.toml
├── sql/
│   └── schema.sql
├── ingestor/
│   ├── Dockerfile
│   ├── main.py            # poll loop
│   └── anomaly.py         # rolling-window detector (§6)
├── api/
│   ├── Dockerfile
│   └── main.py            # FastAPI app
├── dashboard/
│   ├── Dockerfile
│   └── app.py             # Streamlit app
└── tests/
    ├── test_anomaly.py
    └── test_api.py
```

---

## 4. Data model

Two tables. Keep it dumb.

```sql
CREATE TABLE ticks (
  id        BIGSERIAL PRIMARY KEY,
  symbol    TEXT NOT NULL,
  ts        TIMESTAMPTZ NOT NULL,
  price     NUMERIC(12,4) NOT NULL,
  volume    BIGINT,
  UNIQUE (symbol, ts)
);
CREATE INDEX idx_ticks_symbol_ts ON ticks (symbol, ts DESC);

CREATE TABLE alerts (
  id         BIGSERIAL PRIMARY KEY,
  symbol     TEXT NOT NULL,
  ts         TIMESTAMPTZ NOT NULL,
  price      NUMERIC(12,4) NOT NULL,
  z_score    NUMERIC(8,4) NOT NULL,
  message    TEXT NOT NULL
);
CREATE INDEX idx_alerts_ts ON alerts (ts DESC);
```

Schema lives in `sql/schema.sql` and is applied on Postgres container init via the standard `/docker-entrypoint-initdb.d` mount.

---

## 5. Ingestor

### Finnhub API surface

The **ingestor** uses exactly one Finnhub interface — the WebSocket trade stream at `wss://ws.finnhub.io?token={FINNHUB_API_KEY}`. No REST endpoints, no other WebSocket channels in the ingestor.

The **API** additionally proxies three Finnhub REST endpoints — `/stock/market-status`, `/quote`, and `/company-news` — to power an after-hours fallback view in the dashboard (see §7 and §8). Those calls are short-cached in process and never touch the WebSocket path or the ingestor.

Documentation:
- WebSocket reference: https://finnhub.io/docs/api/websocket-trades
- Free-tier rate limits: https://finnhub.io/docs/api/rate-limit
- Pricing / tier breakdown: https://finnhub.io/pricing
- `websockets` Python library: https://websockets.readthedocs.io/

### Protocol

After connecting, send one subscribe frame per symbol:

```json
{"type": "subscribe", "symbol": "AAPL"}
```

Trade events arrive as:

```json
{
  "type": "trade",
  "data": [
    {"s": "AAPL", "p": 187.42, "t": 1716304520123, "v": 100, "c": []}
  ]
}
```

One message can contain multiple trades — always iterate `data`. We persist `s` as `symbol`, `p` as `price`, and `t` (millisecond Unix timestamp) as `ts`. `v` (volume) and `c` (trade conditions) are ignored for v1.

Finnhub may also send non-trade messages (e.g. `{"type": "ping"}`) — ignore any message whose `type` is not `trade`.

### Loop behaviour (async)

The ingestor is a single asyncio task built on the `websockets` library. Pseudocode shape:

```
while True:
    try:
        async with websockets.connect(URL, ping_interval=20, ping_timeout=10) as ws:
            for symbol in SYMBOLS:
                await ws.send(subscribe(symbol))
            reset backoff
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") != "trade":
                    continue
                for trade in msg["data"]:
                    handle_trade(trade)
    except (ConnectionClosed, OSError) as e:
        log("disconnected, reconnecting")
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)   # exponential backoff, cap at 60s
```

For each `trade`:
1. `INSERT ... ON CONFLICT DO NOTHING` into `ticks` (symbol, ts=`to_timestamp(t/1000)`, price=`p`)
2. Feed `p` into the per-symbol anomaly detector (§6)
3. If anomalous, `INSERT` into `alerts`

### Required hardening (do not skip)

These are non-negotiable — they prevent the ingestor from silently dying in production:

- **Auto-reconnect with exponential backoff.** Finnhub disconnects sockets after ~3 hours even when healthy ([GitHub issue #378](https://github.com/finnhubio/Finnhub-API/issues/378)); on disconnect, reconnect and re-send the subscribe frames.
- **`ping_interval=20, ping_timeout=10` on `websockets.connect`.** The library handles ping/pong automatically with these settings.
- **Watchdog.** During US market hours (09:30–16:00 ET, weekdays), if no trade arrives for 60 consecutive seconds, log a warning and force a reconnect ([GitHub issue #35](https://github.com/finnhubio/Finnhub-API/issues/35) — "only pings, no data" stalls happen).
- **Fail fast on missing `FINNHUB_API_KEY`** at startup.
- **Postgres readiness.** On startup, wait for Postgres, apply `sql/schema.sql` if not present (idempotent), then start the WebSocket loop.

### Symbols

Hardcoded for v1: `["AAPL", "MSFT", "GOOGL", "TSLA", "SPY"]` — 5 symbols, well under Finnhub's 50-symbol free-tier cap.

### Off-hours behaviour

Outside market hours the WebSocket stays connected but delivers no trades — that's expected, no special handling needed. The dashboard will simply show flat-line charts until trading resumes. (This is a clean improvement over the REST-polling design, which required a `t == 0` skip rule to handle the same case.)

---

## 6. Anomaly detection (the DS&A piece)

Per-symbol **rolling z-score** detector on log-returns.

- Window size: 60 ticks
- Maintain `sum`, `sum_of_squares`, and a `collections.deque` of the last N log-returns
- On each new return: O(1) update of mean/stddev, compute `z = (r - mean) / stddev`
- Flag when `|z| > 2.5` and `len(window) == N` (i.e., warmed up)

Implementation lives in `ingestor/anomaly.py` as a `RollingZScore` class. Tested in isolation (`tests/test_anomaly.py`) — feed a known series, assert flag fires where expected. No DB or network in the unit tests.

This is the JD's "data structures & algorithms" beat — call it out explicitly in the README.

---

## 7. API (FastAPI)

Five endpoints. The first three read from our Postgres. The last two proxy Finnhub's REST API for the dashboard's after-hours fallback (§8).

| Method | Path | Source | Returns |
|---|---|---|---|
| GET | `/health` | — | `{"status": "ok"}` |
| GET | `/prices/{symbol}?limit=100` | Postgres | last N ticks for symbol, newest first |
| GET | `/alerts?limit=20` | Postgres | last N alerts across all symbols |
| GET | `/quote/{symbol}` | Finnhub `/quote` | current price, day open/high/low, prev close, change, % change |
| GET | `/news/{symbol}` | Finnhub `/company-news` | last 7 days of company headlines, newest first, capped at 10 |
| GET | `/market-status?exchange=US` | Finnhub `/stock/market-status` | `is_open`, `session` (pre-market / regular / post-market / closed), `holiday` |

- Use FastAPI's dependency injection for the DB connection.
- Pydantic response models.
- The Finnhub-backed endpoints share one `httpx.AsyncClient` (lifespan-managed) and an in-process TTL cache (30s for /market-status, 60s for /quote, 5 min for /news). Returns `502` on any outbound HTTP failure.

### End-to-end test (no mocks)

`tests/test_api.py` is a **real end-to-end test** — no mocking, no in-memory shims. It must exercise the same code path that runs in production:

1. CI runs a real **Postgres 16** as a GitHub Actions service container (locally, the test spins one up via `testcontainers-python` or reads `TEST_DATABASE_URL` from a developer-supplied compose stack).
2. The test applies `sql/schema.sql` to that real DB.
3. The test inserts a few known rows into `ticks` and `alerts` using the same `psycopg` driver the app uses.
4. The test starts the FastAPI app pointed at that real DB and makes **real HTTP requests** via `httpx.AsyncClient` against `app` (ASGI transport — exercises the full middleware/routing stack, no test-mode shortcuts).
5. Assertions verify the response JSON matches the rows we inserted, including ordering and `limit` behavior.

Cover all three endpoints (`/health`, `/prices/{symbol}`, `/alerts`). No mocks of the DB, the driver, or the network layer. If something doesn't work in this test, it doesn't work in production.

---

## 8. Dashboard (Streamlit)

One page. Auto-refresh every 10s (`st.autorefresh` or a manual rerun).

- **Top:** symbol selector dropdown.
- **Main (live mode):** Plotly line chart of last ~200 ticks for the selected symbol. Overlay red dots at timestamps where alerts fired.
- **Main (after-hours mode):** when `/market-status` reports `is_open=false` (or returns no live ticks even during the regular session, e.g. a cold-start ingestor), render a watchlist view instead: a row of `st.metric` quote cards for all five symbols (current price, % change colored green/red, day range, prev close) with the selected symbol's card visually highlighted, plus a "News: {symbol}" feed of the 10 most recent headlines from `/news/{symbol}`. The banner copy varies by `session` (pre-market / post-market / closed / holiday name) so it reads honestly instead of just "market closed." The page auto-flips back to live mode the next refresh once the market reopens and trades flow.
- **Side panel:** "Recent Alerts" — last 10 alerts across all symbols, newest first.
- **Footer:** small attribution text — `Market data: Finnhub` (linked to https://finnhub.io). Finnhub's free tier is informally "personal/non-commercial"; a public portfolio URL is a grey area, and this attribution is the standard courtesy that removes any ambiguity.

Reads exclusively from the API (`http://api:8000`). No DB access from the dashboard, and no direct Finnhub access either — the after-hours data flows dashboard → API → Finnhub.

---

## 9. README (this is the portfolio surface — invest here)

The README is what a recruiter actually sees. It must:

- Open with a 1-sentence elevator pitch + a screenshot or short GIF of the dashboard.
- Have a **"What this demonstrates"** section explicitly listing the JD-relevant skills (Python, SQL, microservices, Docker, CI/CD, DS&A in the anomaly detector, financial markets domain). Be direct — this is a portfolio.
- Have a **Quickstart** that's literally `docker-compose up` and a URL.
- Have an **Architecture** section with the ASCII diagram from §1.
- Have a short **"Design notes"** section explaining the rolling z-score choice (O(1) updates, why log-returns, etc.) — this is the interview-talking-point section.

---

## 10. Docker / docker-compose

`docker-compose.yml` defines four services: `postgres`, `ingestor`, `api`, `dashboard`. Postgres mounts `./sql/schema.sql` into `/docker-entrypoint-initdb.d/`. Services share a default network; the API is reachable as `api:8000` from the dashboard. Expose `8000` (API) and `8501` (Streamlit) on the host.

Use one shared base Dockerfile pattern (slim Python image, copy code, `pip install`). No multi-stage builds, no Alpine — not worth the time.

---

## 11. Deployment — AWS Lightsail Container Service

**Why Lightsail and not raw ECS / Fargate / Cloud Run / a $4 VPS:**
- The Goldman JD explicitly lists **AWS, Docker, CI/CD** as preferred qualifications. Lightsail Container Service lets us honestly claim all three with the least time investment.
- It runs a multi-container deployment spec natively — our 4-service stack maps cleanly without rewriting into a different orchestrator.
- Always-on, no cold starts, free HTTPS via a `*.cs.amazonlightsail.com` subdomain.
- **First 3 months free** on the Nano plan, then $7/mo. Long enough to cover the Goldman application cycle.
- ECS Fargate would be more impressive on paper but burns half a day on ALB + IAM + task definitions. Lightsail is the right cost/benefit for a one-day build.

**Topology:**
- One Lightsail **Container Service** (Nano, $7/mo) runs `ingestor`, `api`, and `dashboard` containers. Public endpoint points at the `dashboard` container on port 8501.
- One Lightsail **Instance** ($5/mo, smallest) runs Postgres 16 in Docker with a mounted volume for persistence. Reachable from the container service via Lightsail's VPC peering.
- Total: ~$12/mo after the 3-month free trial.

**Deployment flow (driven by CI — see §12):**
1. GitHub Actions builds each image
2. `aws lightsail push-container-image` pushes to the Lightsail registry
3. `aws lightsail create-container-service-deployment` rolls the new spec
4. Secrets (`FINNHUB_API_KEY`, `DATABASE_URL`) live in the Lightsail container service environment, not in the repo

**Fallback if AWS account setup is blocking on the day:** A Hetzner CX22 (€3.49/mo) running the unchanged `docker-compose.yml` behind Caddy for auto-TLS. Costs less but loses the "AWS" keyword — only take this path if AWS is genuinely blocked.

The live URL goes at the top of the README.

---

## 12. CI/CD (GitHub Actions)

Single workflow, `.github/workflows/ci.yml`, on push + PR:

1. Set up Python 3.14
2. Install deps
3. `ruff check`
4. `pytest` — Postgres 16 service container running for the real end-to-end API test (§7)
5. `docker compose build` to prove all images build

Separate workflow `deploy.yml` on push to `main`:
1. Build + tag images
2. `aws lightsail push-container-image` for each service
3. `aws lightsail create-container-service-deployment` with the updated image tags
4. AWS creds via repository secrets (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)

This is the JD's "CI/CD" keyword, end to end.

---

## 13. Done criteria

The project is "done" when all of these are true:

- [ ] `docker-compose up` brings up all four services cleanly on a fresh clone.
- [ ] Dashboard at `localhost:8501` shows live charts updating every 10s.
- [ ] At least one alert appears within the first few minutes of running (force one in dev by lowering the z-score threshold temporarily if needed for the screenshot).
- [ ] `pytest` passes locally and in CI, including the real end-to-end API test against a real Postgres.
- [ ] README has a screenshot or GIF, the "What this demonstrates" section, a working quickstart, and the live URL.
- [ ] Repo is pushed to GitHub with a clean commit history.
- [ ] Deployed to AWS Lightsail; public URL loads the dashboard with live data.

---

## 14. Explicitly out of scope

To prevent scope creep mid-build:

- No user auth, no accounts.
- No ORM (SQLAlchemy, etc.) — raw SQL via `psycopg`.
- No message queue (Kafka, Redis, etc.) — Postgres is the bus.
- No Kubernetes, no Terraform, no IaC. AWS resources are clicked once or shelled in via the CLI; the workflow file is the only "infra as code."
- No FastAPI WebSocket endpoints. The only WebSocket in the system is the outbound connection from the ingestor to Finnhub. The dashboard polls the internal REST API at 10s — Streamlit doesn't consume WebSocket naturally, and internal polling has no rate-limit or latency cost.
- No real ML model. The z-score detector is the entire "intelligence."
- No backtesting, no trading logic, no portfolio tracking.
- No multi-symbol correlation, no cross-asset analysis.
- No frontend build step. Streamlit is the UI.
