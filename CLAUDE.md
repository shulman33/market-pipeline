# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A portfolio project being built to support a job application for the **Goldman Sachs Software Engineer Analyst** role (`job-description.md`). Every architectural choice is justified by a specific JD keyword the project aims to demonstrate.

**The repo is currently pre-implementation.** Only `SPEC.md` and `job-description.md` exist. `SPEC.md` is the authoritative build plan — read it end-to-end before writing any code. The build is scoped to one day; the spec has been deliberately whittled down and §14 lists what's explicitly out of scope.

## How to operate in this repo

1. **`SPEC.md` is the source of truth.** Section numbers are stable; reference them when proposing changes (e.g. "per §5, the ingestor skips `t == 0`"). If a request appears to conflict with the spec, surface the conflict before coding around it.
2. **Resist scope creep.** §14 is an anti-creep guardrail. Things excluded there (auth, ORM, MQ, K8s, ML model, WebSocket ingestion, backtesting) are excluded *deliberately* to keep the build to one day — don't add them back without explicit user direction.
3. **Tradeoffs already settled** (don't re-litigate without reason):
   - Finnhub over yfinance — yfinance is unofficial Yahoo scraping with no SLA.
   - **Finnhub WebSocket over REST polling** — vendor explicitly recommends WS; earns the JD's "low-latency" keyword honestly. The `websockets` async library connects out to `wss://ws.finnhub.io`. This is the only WebSocket in the system.
   - **No FastAPI WebSocket endpoints.** Dashboard polls our REST API at 10s. Streamlit doesn't consume WebSocket naturally, and internal polling has no rate-limit cost — adding a WS server in our API for one Streamlit client doesn't pay off.
   - AWS Lightsail Container Service over ECS/Fargate/Cloud Run — Lightsail hits the AWS/Docker/CI/CD keywords for ~$12/mo without burning half a day on ALB/IAM.
   - Raw `psycopg` over an ORM — less code, and SQL is itself a JD keyword.
   - Streamlit as the UI — the JD lists no frontend framework requirement, so React/Vue would be effort without keyword payoff. Streamlit fully satisfies the live-dashboard objective.
   - Postgres as the message bus — no Kafka/Redis.

## Architecture (per SPEC §1)

Three Python services + Postgres, wired by `docker-compose.yml`:

- **ingestor** — maintains a persistent WebSocket connection to `wss://ws.finnhub.io` for 5 hardcoded symbols (AAPL, MSFT, GOOGL, TSLA, SPY). On each trade event: writes `ticks`, runs the anomaly detector, writes `alerts`. Async loop with auto-reconnect + exponential backoff.
- **api** (FastAPI) — three endpoints only: `/health`, `/prices/{symbol}`, `/alerts`. Reads from Postgres.
- **dashboard** (Streamlit + Plotly) — reads exclusively from the API (never the DB), auto-refreshes every 10s.

The dashboard never touches the DB. The ingestor never touches the API. Cross-service boundaries are HTTP + Postgres, nothing else.

## Key design points to preserve when building

- **The anomaly detector (§6) is the deliberate DS&A showcase.** It must use O(1) rolling-window updates (running `sum` and `sum_of_squares` over a `deque`). Don't replace it with a library call — that erases the JD-keyword payoff.
- **`tests/test_api.py` is a real end-to-end test, not a smoke test (§7).** No mocks of the DB, driver, or HTTP layer. CI runs Postgres 16 as a service container; locally, `testcontainers-python` brings one up. If a future change tempts you to mock around test friction, fix the friction instead.
- **Ingestor must auto-reconnect with backoff and run a stale-stream watchdog** (§5). Finnhub disconnects sockets after ~3 hours even when healthy, and occasionally goes "pings only, no data" — silent failure here would leave the dashboard frozen on stale data. Reconnect must re-send the subscribe frames. During market hours, force a reconnect if no trades arrive for 60 consecutive seconds.
- **Ignore non-trade messages** from the Finnhub WebSocket — only process frames where `type == "trade"`, and iterate the `data` array (one message can carry multiple trades).
- **Dashboard shows a `Market data: Finnhub` attribution footer** (§8). Finnhub's free tier is informally personal/non-commercial; the attribution is the mitigation for a publicly-hosted portfolio URL.

## Target commands (once implemented per SPEC)

Local dev:
- `docker compose up` — run the full stack; dashboard at `localhost:8501`, API at `localhost:8000`
- `pytest` — run all tests including the real E2E API test against a Postgres container
- `pytest tests/test_anomaly.py::test_<name>` — single test
- `ruff check` — lint

Deploy (per §11–12):
- `aws lightsail push-container-image --service-name <svc> --label <label> --image <local-image>`
- `aws lightsail create-container-service-deployment ...`
- Driven by `.github/workflows/deploy.yml` on push to `main`

## Required env vars (per SPEC)

- `FINNHUB_API_KEY` — free key from finnhub.io, no credit card required
- `DATABASE_URL` — standard Postgres URL; in local dev points at the compose Postgres service
- In production: stored as Lightsail container service environment variables, not in the repo

## What lives where

- `SPEC.md` — authoritative build plan (sections 1–14)
- `job-description.md` — the Goldman JD; the source of every keyword the project is targeting
- `README.md` — *to be written*; the portfolio-facing surface, must include screenshot/GIF, live URL, and the "What this demonstrates" section per SPEC §9

## Coding principles (apply everywhere)

**Think in types first.** Before writing any function, sketch the input and output types and the data structures that flow between them. When the types are right the code falls out.

**Modular, not fragmented.** Split when a unit has one job and a clear interface. Do not split for the sake of splitting. A 40-line function that reads top-to-bottom is better than five 8-line functions that force the reader to jump around.

**DRY, but only after the third repetition.** Two similar blocks are a coincidence; three is a pattern. Premature abstraction is worse than duplication because it locks in the wrong shape. The matcher logic in particular must be byte-for-byte identical between Python and Rust, which is intentional duplication and not a DRY violation.

**Comments explain why, not what.** Well-named functions and variables already say what the code does. Only comment when a reader would otherwise be confused: a non-obvious invariant, a workaround, a deliberate deviation from the obvious approach. Never comment out code; delete it (git remembers).

**No emojis. No em dashes.** In code, comments, commit messages, docs, or any generated prose. Use commas, semicolons, parentheses, or new sentences instead.

**Try/except is for specific, expected failure modes.** Wrap only the smallest expression that can actually throw the exception you are handling, catch the specific exception class, and either recover meaningfully or re-raise with added context. 

**Always use context7 for up to date documentation**
