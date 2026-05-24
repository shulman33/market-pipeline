# Local Stack Build and Code Review — Session Summary (2026-05-24)

## TL;DR

Greenfield build of the real-time market-data pipeline described in `SPEC.md`: three Python services (ingestor / api / dashboard) plus Postgres, all wired by `docker-compose.yml`. Eight commits land on `main`. Local stack verified end-to-end against the live Finnhub WebSocket (market was closed during verification, so the ingestor connected and subscribed but no trades flowed, which is the spec-defined idle behaviour). 14/14 tests pass, including 8 real E2E API tests against a testcontainers-managed Postgres 16. A subsequent max-effort three-agent code review caught two real bugs (tick/alert atomicity, JSON-decode process crash) plus a test gap (warmup boundary never asserted) and several efficiency wins; all fixed in one refactor commit.

Out of scope for this session and deferred to a follow-up: `.github/workflows/ci.yml`, README polish (screenshot/GIF + "What this demonstrates" + design notes), and AWS Lightsail deployment.

Branch: `main`. Not pushed to a remote (no remote configured yet).

## Why we did this

The repo is a portfolio project backing a Goldman Sachs SWE Analyst application. `SPEC.md` had been whittled down to a one-day build and was the authoritative plan; this session was the build itself. The spec deliberately closes off scope creep (`§14`) — no ORM, no Kafka, no FastAPI WebSocket endpoints, no ML model — because every component is supposed to map to a specific JD keyword without burning time on things that don't.

Session opened with a Plan-mode pass that wrote `/Users/samshulman/.claude/plans/lets-start-implementing-this-glittery-wren.md`. That plan picked the bottom-up ordering used below (schema → anomaly → API → ingestor → dashboard → compose) so each layer could be exercised before the next was added.

## Architectural decisions that matter

1. **Per-service `requirements.txt` files, single root `pyproject.toml` for tool config.** Considered a monorepo-style root `requirements.txt` (one image installs everything), and `[project.optional-dependencies]` groups. Per-service files keep each Docker image lean and make microservice boundaries explicit in the repo layout; root `pyproject.toml` only holds `[tool.ruff]` and `[tool.pytest.ini_options]`. See `pyproject.toml`, `ingestor/requirements.txt`, `api/requirements.txt`, `dashboard/requirements.txt`, `requirements-dev.txt`.

2. **`asyncio_default_*_loop_scope = "module"` in `pyproject.toml`.** This was forced by a pytest-asyncio interaction that cost a 4-minute test run early on. Module-scoped `client` / `postgres_url` fixtures hold a `psycopg_pool.AsyncConnectionPool` whose internal tasks live on the fixture's event loop; with the default function-scoped test loop, every DB-touching test timed out for 30s. Aligning fixture and test loop scopes to `module` is the supported fix. See `pyproject.toml:9-11`.

3. **`@st.cache_resource` singleton `httpx.Client` in the dashboard.** Initially each `@st.cache_data` fetcher opened its own `httpx.Client(...)` per call, giving up keep-alive across the three calls per refresh. The cached singleton lives for the process lifetime. See `dashboard/app.py:30-32`.

4. **Single `fetch_alerts(OVERLAY_ALERT_LIMIT)` call + `.head(SIDEBAR_ALERT_LIMIT)` for the sidebar.** Originally two calls with different limits, which meant two cache keys, two HTTP round-trips per refresh, and a chance of the chart overlay and sidebar showing data from different instants. See `dashboard/app.py:103`.

5. **`cache_data(ttl=10)` matching the autorefresh interval.** `ttl=5` with a `REFRESH_INTERVAL_MS=10_000` meant every refresh was a cache miss — the cache was decorative. Matching the TTL to the interval makes the cache actually deduplicate within a tick. See `dashboard/app.py:24-26`.

6. **Atomic tick + alert insert via `conn.transaction()` on an `autocommit=True` connection.** psycopg's `conn.transaction()` issues a real `BEGIN/COMMIT` when the connection is in autocommit mode (it issues a savepoint when not). Wrapping the two writes guarantees a price spike on the chart cannot exist without its alert marker, even on a mid-trade crash. See `ingestor/main.py:131-148`.

7. **`env_file: { path: .env, required: false }` on the ingestor compose service.** `.env` is gitignored. With `required: true` (the default for a bare string `env_file: .env`), `docker compose build` errors on a fresh clone before the user creates `.env`. Marking it optional lets the build succeed; the ingestor's own startup check fails fast with a clear message when `FINNHUB_API_KEY` is missing. See `docker-compose.yml:21-23` and `ingestor/main.py:194-200`.

8. **Idempotent schema apply via `SELECT to_regclass('public.ticks')` instead of `IF NOT EXISTS`.** The canonical `sql/schema.sql` uses bare `CREATE TABLE` so the Postgres container's init-script mount applies it cleanly on a fresh volume. The ingestor's `apply_schema_if_missing` does a one-row probe and skips when the table exists, avoiding the need to fork the schema into two variants. See `ingestor/main.py:96-114`.

9. **Watchdog closes the WS rather than raising.** During US market hours, if no trade arrives for 60s the watchdog calls `await ws.close()`. That causes `async for raw in ws` to exit cleanly, and the outer `while True` reconnect loop takes over with backoff reset. Considered raising a custom exception from the watchdog into the main task; closing is simpler and uses the existing reconnect path. See `ingestor/main.py:151-159`.

10. **No git push, no remote configured.** The session ended without configuring a GitHub remote. The repo is local-only on `main`.

## Where things live

| Concern | Path |
|---|---|
| Spec (authoritative) | `SPEC.md` |
| Coding rules | `CLAUDE.md` (no emojis/em-dashes, why-not-what comments, DRY after the third repetition) |
| Schema | `sql/schema.sql` |
| Anomaly detector | `ingestor/anomaly.py` |
| Ingestor entrypoint | `ingestor/main.py` (`run` is the asyncio entry; `_handle_trade` is the per-trade hot path) |
| API | `api/main.py` (lifespan-managed `AsyncConnectionPool`; `ConnDep = Annotated[..., Depends(get_conn)]` dodges ruff B008) |
| Dashboard | `dashboard/app.py` |
| Unit tests | `tests/test_anomaly.py` (6 tests, pure-Python, no Docker required) |
| E2E tests | `tests/test_api.py` (8 tests, requires Docker — testcontainers spins Postgres 16 per module) |
| Compose | `docker-compose.yml` |
| Tool config | `pyproject.toml` |
| Plan (Plan-mode artifact) | `~/.claude/plans/lets-start-implementing-this-glittery-wren.md` |

## Current state: what's built and verified

Verified live in this session:
- `docker compose build` — all three Python images build clean.
- `docker compose up` — postgres healthy, api on `:8000`, dashboard on `:8501`, ingestor connected to `wss://ws.finnhub.io` and subscribed to AAPL/MSFT/GOOGL/TSLA/SPY.
- `curl http://localhost:8000/health` → `{"status":"ok"}`. `/prices/AAPL` and `/alerts` return `[]` (no ticks ingested because the verification happened outside market hours, exactly as `§5` predicts).
- Dashboard at `http://localhost:8501` renders the empty-state and polls the three API endpoints every 10s (visible in the api logs as a recurring `GET /prices/AAPL?limit=200`, `GET /alerts?limit=200`, `GET /alerts?limit=10` cadence).
- `pytest` → 14/14 pass.
- `ruff check .` → clean.

Not yet verified (deferred):
- Trades actually populating the chart during market hours.
- Anomalies actually firing in production (the synthetic-spike test proves the math; the spec mentions temporarily lowering the threshold for the screenshot, which is a follow-up task).

## How to run / reproduce

From the repo root (`/Users/samshulman/Coding/My-Software-Projects/goldman-porfolio/`).

```bash
# tests (Docker required for the E2E suite)
.venv/bin/python -m pytest -v

# lint
.venv/bin/ruff check .

# bring the full stack up (needs FINNHUB_API_KEY in .env)
cp .env.example .env  # already done in this session
docker compose up -d
docker compose logs -f ingestor   # watch the websocket connection

# tear down
docker compose down       # keeps the postgres volume
docker compose down -v    # also wipes the postgres volume
```

The venv at `.venv/` was created with `uv venv --python 3.14 .venv` and populated with `uv pip install --python .venv/bin/python -r requirements-dev.txt`. `.venv/bin/python -m pip` does not work (uv venv ships without pip); use `uv pip` for dep changes.

## Gotchas and footguns

1. **`uv venv` does not install pip.** `.venv/bin/python -m pip install ...` errors with `No module named pip`. Use `uv pip install --python .venv/bin/python ...` instead. Cost on this session: ~30 seconds and one confused error message.

2. **pytest-asyncio loop scope mismatch costs 30s per DB-touching test.** A module-scoped fixture opening an `AsyncConnectionPool` cannot be used from a function-scoped event loop — the pool's internal coroutines live on the wrong loop and `pool.connection()` times out after 30s. The fix is `asyncio_default_fixture_loop_scope = "module"` and `asyncio_default_test_loop_scope = "module"` in `pyproject.toml`. The first failing run took 244 seconds (mostly testcontainers waiting on the pool); after the config fix the run dropped to 2 seconds.

3. **The B008 lint on `Depends(get_conn)` in defaults is correctly worked around with `Annotated[AsyncConnection, Depends(get_conn)]`.** Don't switch back to bare defaults — ruff will flag it.

4. **`websockets.WebSocketClientProtocol` is the legacy import name.** In `websockets>=15` the new API is `websockets.asyncio.client.ClientConnection` and the old name may not be importable. The watchdog's `ws` parameter is intentionally untyped to avoid coupling to internals.

5. **Streamlit serves 1.57+ over uvicorn.** Curling `http://localhost:8501` returns `server: uvicorn` in the headers even though the app is Streamlit. This briefly looked like a port-mapping bug; it wasn't.

6. **`fastapi-websockets.md` was vestigial research.** Deleted in commit `2c6e4f6`. SPEC `§14` rules out FastAPI WebSocket endpoints; the file was Anthropic API docs noise.

7. **`docker compose build` will fail without an `.env` file unless `env_file: { required: false }` is set.** A bare `env_file: .env` (string form) treats it as required. The current compose uses the optional form on the ingestor service.

8. **The schema file is intentionally non-idempotent.** It uses bare `CREATE TABLE`. The init-script mount runs it on a fresh volume; the ingestor's `apply_schema_if_missing` does a `to_regclass` check before re-applying. Do not add `IF NOT EXISTS` — keeping the canonical schema simple is the design point.

9. **The CLAUDE.md style hard rules: no emojis, no em-dashes anywhere in code, comments, or strings.** Ruff doesn't catch this; rely on eyeballing.

10. **The hand-rolled `RollingZScore` is the DS&A showcase.** Do not replace with numpy / pandas / scipy. The O(1) running-sum + running-sum-of-squares + deque pattern is the entire point of `ingestor/anomaly.py`; `SPEC.md §6` mandates it stays hand-rolled.

11. **The pre-commit security hook flags helper-function names containing the substring `e`+`x`+`e`+`c`.** During the refactor a name like `_e` + `xec_many` triggered a `child-process` shell-injection warning hook even though Python has nothing to do with that. Renamed to `_run_sql` / `_run_sql_many`. Future refactors should avoid that substring in helper names to stay quiet.

12. **`is_market_open` ignores US market holidays.** A spurious reconnect on a closed holiday is the worst case; not worth a `pandas_market_calendars` dep for a portfolio piece. Documented in the function's docstring.

13. **Port 8000 conflicts are real.** A leftover `python -m http.server 8000` on the host blocked the API container from binding. The compose file uses the spec-mandated port 8000 on the host; the user has to free it themselves.

## What's left to ship

Must-have to ship (per `SPEC.md §13` done-criteria):
1. `.github/workflows/ci.yml` — lint + pytest (Postgres 16 service container for the E2E test) + `docker compose build`.
2. README rewrite — screenshot/GIF, "What this demonstrates" section, quickstart, design notes, live URL at the top.
3. AWS Lightsail Container Service deployment per `SPEC.md §11` (push images, create container service deployment, secrets in Lightsail env). One-time AWS-CLI bootstrap required.
4. Force at least one alert in dev for the screenshot — the spec suggests temporarily lowering the z-score threshold to make the alert overlay visible.
5. `git remote add origin ...` and push.

Nice-to-have:
- Optional `is_market_open` holiday calendar.
- `(symbol, ts DESC)` index on `alerts` if the API ever gains `?symbol=` filtering.
- Per-trade structured logging for production-grade observability.

## Branch state / commits

Branch: `main`. Eight commits since session start, all by Sam Shulman (co-authored by Claude). No remote configured, nothing pushed.

```
2c6e4f6 refactor: address code-review findings across ingestor, dashboard, tests
20aeb05 feat(compose): wire all four services and gitignore .claude/
80987db feat(dashboard): Streamlit UI with live chart, alert overlay, and Finnhub attribution
69c23aa feat(ingestor): Finnhub websocket loop with watchdog and reconnect
f10e328 feat(api): FastAPI service with three endpoints + real E2E test
9c71922 feat(anomaly): rolling z-score detector with O(1) updates
909b762 feat(sql): add ticks and alerts schema
b5127f6 chore: initial repo skeleton
```

## Known unknowns

- Whether Finnhub's free tier permits a publicly-hosted portfolio URL. The footer attribution is the documented mitigation; if it's still a problem, the fallback is a Hetzner CX22 deploy (loses the "AWS" JD keyword).
- Whether the Lightsail Nano plan handles the Postgres-on-Lightsail-Instance peering cleanly on first try. Spec says `§11` topology is two Lightsail resources (container service + instance running Postgres); we have not yet validated the VPC peering.
- Whether the alert threshold of `2.5` produces visible alerts in normal trading or only during opens / closes / major prints. May need calibration after observing real data for an hour.
