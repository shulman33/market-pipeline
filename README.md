# market-pipeline

> A four-service stack for real-time market data and limit-order-book matching. Python ingestor on the Finnhub WebSocket, FastAPI, a Java matching engine with price-time priority, Streamlit dashboard, Postgres. Deployed on AWS Lightsail.

### → [Read the full project writeup](https://shulman33.github.io/market-pipeline/)

The showcase page is the canonical entry point. It carries the live URL,
architecture diagram, design notes, code samples, and the JD-keyword payoff in
one editorial-format page. This file only covers what a GitHub-native reader
needs to clone and run the repo.

- Live demo: http://98.83.89.166:8501
- Project showcase: https://shulman33.github.io/market-pipeline/
- CI: https://github.com/shulman33/market-pipeline/actions

## Quickstart

Requires Docker and a free Finnhub API key (no credit card needed).

```bash
git clone https://github.com/shulman33/market-pipeline.git
cd market-pipeline
cp .env.example .env
# Edit .env: set FINNHUB_API_KEY=<your key from https://finnhub.io>
docker compose up -d --build
```

Then open:

- Dashboard: http://localhost:8501
- API: http://localhost:8000/health
- Matching engine: http://localhost:8080/health

## Tests

```bash
# Python: 21/21. Lint + unit tests + real E2E against a testcontainers Postgres
.venv/bin/ruff check .
.venv/bin/python -m pytest -v

# Java: 25/25. The limit-order-book DS&A
cd matching-engine && mvn test
```

The Python end-to-end suite uses no mocks: it spawns a real Postgres 16
container and (for the matching-engine tests) the locally-built Java image,
then exercises the actual `psycopg` driver and ASGI stack.

## Repo layout

```
.
├── README.md                  # this file
├── SPEC.md                    # the one-day build plan that drove the project
├── docs/index.html            # the showcase page (GitHub Pages source)
├── docker-compose.yml         # four services + Postgres
├── sql/schema.sql             # five tables, two subsystems
├── ingestor/                  # Finnhub WebSocket + rolling z-score
├── api/                       # FastAPI
├── matching-engine/           # Java limit-order-book service
├── dashboard/                 # Streamlit multi-page app
├── tests/                     # pytest (unit + real E2E)
├── .github/workflows/ci.yml   # lint + pytest + mvn test + compose build
└── session-summaries/         # detailed writeups, one per build session
```

## Enabling the showcase on GitHub Pages

The showcase lives at `docs/index.html`. To serve it from
`https://shulman33.github.io/market-pipeline/`:

1. Repo Settings, Pages.
2. Source: Deploy from a branch.
3. Branch: `main`, Folder: `/docs`.
4. Save.

## Deployment

Currently running on AWS Lightsail (Ubuntu 24.04, 2 GB), the entire
`docker-compose.yml` brought up unchanged on one instance. See the
[Deployment section of the showcase](https://shulman33.github.io/market-pipeline/#quickstart)
and the per-session writeups in `session-summaries/` for the deploy story.

## Status

- 25/25 JUnit, 21/21 pytest, ruff clean
- CI green on every push to `main`
- Live on the URL at the top of this file

Market data: [Finnhub](https://finnhub.io).
