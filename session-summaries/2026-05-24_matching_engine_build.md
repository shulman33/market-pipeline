# Matching Engine Build — Session Summary (2026-05-24)

## TL;DR

Greenfield build of a Java limit-order-book matching engine as a fourth compose service alongside the existing Finnhub stack. Java 17 + Maven + Javalin + JDBC + HikariCP, ~30 source files. The engine implements price-time priority matching with O(log n) submits and O(1) cancels using a per-side `TreeMap<BigDecimal, PriceLevel>` plus an order-id `HashMap` and intrusive doubly-linked FIFO queues at each price level. A synthetic order generator drives the book at ~50 ms cadence per symbol (70 % limit, 20 % market, 10 % cancel). Persistence writes to three new tables (`me_orders`, `me_trades`, `me_book_snapshots`) on the shared Postgres. Streamlit became a multi-page app: existing Finnhub view is page 1, a new "Matching Engine" page 2 shows top-of-book, depth ladder, and recent trades at 2 Hz autorefresh.

Plan-mode designed the build; the plan artifact lives at `~/.claude/plans/lets-build-the-matching-snug-oasis.md`. Seven incremental steps were executed in order, each ending in a runnable state. After everything was green a three-agent max-effort code review caught nine issues, all addressed in a follow-up cleanup pass: hand-rolled unlink in `OrderBook.match` collapsed onto `PriceLevel.unlink`, `AtomicLong` replaced with plain `long` inside the `synchronized` class, `TradeLog` reentrance removed, 9-param `OrderJournal.record` collapsed to an `OrderEvent` record, `prepareThreshold=1` added to Hikari for server-side prepared-statement caching, schema-apply and httpx-client-singleton patterns extracted to `tests/conftest.py` and `dashboard/_shared.py`, build artifacts removed from git.

Status: matching-engine commit (`a783b3c`) is on `main`. The review cleanup is staged-but-uncommitted (54 changed files, of which 40 are deletions of accidentally-committed `target/` artifacts now under `.gitignore`). 25/25 JUnit + 21/21 pytest green. Full compose stack runs locally and was visually verified at 2 Hz against the dashboard page.

## Why we did this

The previous session (`session-summaries/2026-05-24_local_stack_build_and_review.md`) finished the three Python services backing the Goldman SWE Analyst portfolio application. The JD lists "Java, Python, C++, or C#" as a basic qualification, and Java was the most under-demonstrated keyword in the build. We brainstormed several standout features (matching engine, OHLC aggregator, observability, ML predictor, replay framework). The user picked the matching engine because (a) it is the most "Goldman-coded" feature on the list and (b) it stands on its own as a pure DS&A showcase, separable from the Finnhub stack.

The user explicitly does not know C++ but does know Java, which closed off the original "C++ stats engine" pitch. The user asked to be taught what an order book matching engine is and what OHLC means before committing; that explainer happened before plan mode.

## Architectural decisions that matter

1. **Java 17, not 21.** Local OpenJDK is 17 (Homebrew). Both are LTS; Java 17 still has records, sealed types, pattern matching for `switch`, text blocks. The DS&A doesn't benefit from 21 features, and aligning local Java with the Dockerfile keeps `mvn test` runnable without an extra install. See `matching-engine/pom.xml:13-14` and `matching-engine/Dockerfile`.

2. **Javalin over Spring Boot.** Spring is what Goldman actually uses, but the framework is not the point of this sub-project — the order book is. Javalin keeps `HttpServer.java` at ~130 lines with explicit route wiring; Spring would have buried the DS&A behind annotations. See `matching-engine/src/main/java/com/portfolio/matching/api/HttpServer.java`.

3. **Maven over Gradle.** Maven is more universally recognized and Goldman job listings frequently mention it. The pom uses `maven-shade-plugin` to produce a fat jar (`matching-engine-0.1.0-shaded.jar`) for the Docker runtime stage.

4. **Standalone subsystem, not integrated with the Finnhub pipeline.** The engine has its own tables (`me_` prefix), its own HTTP API, and its own simulation driver. SPEC §14 excludes "no message queue, no cross-symbol correlation"; rather than relax that, the matching engine sits beside the Finnhub stack as a parallel sub-project that happens to share a Postgres. This also preserves the option to lift it out into its own repo later. See `sql/schema.sql:20-61` for the table additions under the `-- Matching engine` header.

5. **Synthetic order generator, not Finnhub-tick-driven.** Considered bridging the Finnhub tick stream to feed market orders, rejected because (a) outside US market hours nothing flows and the demo dies, (b) it would couple the two subsystems and undermine decision 4, and (c) the synthetic generator is deterministic with `ME_SEED`, which gives reproducible book state for screenshots and tests. See `matching-engine/src/main/java/com/portfolio/matching/sim/SyntheticOrderGenerator.java`.

6. **`Engine` facade pattern.** The HTTP layer and the synthetic generator both submit orders. Without `Engine`, each caller would have to remember to also `tradeLog.appendAll(...)`, `orderJournal.record(...)`, `tradeWriter.writeAll(...)`. The facade funnels both callers through one place so persistence and the in-memory log can never silently drift. See `matching-engine/src/main/java/com/portfolio/matching/engine/Engine.java`.

7. **`OrderJournal` and `TradeWriter` as interfaces with `NOOP` constants.** Without `DATABASE_URL`, the engine runs the no-op implementations and `App.java` is the only branch that depends on the env var. This is more code than a nullable field but reads cleaner at the call site (no `if (journal != null)` peppered everywhere). See `matching-engine/src/main/java/com/portfolio/matching/persistence/OrderJournal.java:13`.

8. **`AtomicLong` reverted to plain `long`.** Initial code used `AtomicLong nextOrderId` for the order-id counter. Code review pointed out that every public method of `OrderBook` is already `synchronized`, so the atomic was misleading (it implies lock-free intent that isn't there). Plain `long nextOrderId++` after the cleanup pass. See `matching-engine/.../book/OrderBook.java:39`.

9. **Hand-rolled unlink in `match()` collapsed onto `PriceLevel.unlink()`.** The initial `match()` had 14 lines of inline pointer surgery to "avoid double-decrement of `totalQuantity`." That was actually safe to delete: `decreaseQuantity(fillQty)` zeros the maker's remaining quantity before the `if (maker.remainingQuantity() == 0)` check, so `unlink(maker)` subtracts 0 from `totalQuantity`. Pre-cleanup the two unlinks could silently diverge; post-cleanup there is one pointer-surgery path. See `matching-engine/.../book/OrderBook.java:148-152`.

10. **`OrderEvent` record collapsed the 9-positional-arg `OrderJournal.record(...)`.** The journal now takes one named record instead of nine positional parameters. Same data, much harder to mis-order at the call site. See `matching-engine/.../persistence/OrderEvent.java`.

11. **`prepareThreshold=1` on Hikari config.** Without this, every `c.prepareStatement(SQL)` call hits the pgjdbc client cache but never flips to server-side named prepared statements (the driver's threshold defaults to 5 reuses). The current code-then-close-before-pool-return pattern resets the count. Setting the threshold to 1 makes the very first execute use a named server-side plan; subsequent inserts skip parse + plan. See `matching-engine/.../persistence/Db.java:42-44`.

12. **Streamlit multi-page via the `pages/` convention.** Considered building a single page with a tab widget. Rejected: Streamlit's `pages/*.py` auto-discovery is the idiomatic shape for multi-view apps, and it gives the dashboard a sidebar with both views one click apart. Filename `1_matching_engine.py` is the canonical "first additional page" convention; the leading digit controls sort order in the sidebar. See `dashboard/pages/1_matching_engine.py`.

13. **Refresh cadence 500 ms (2 Hz) on the matching engine page.** The Finnhub page is 10 s (Finnhub free-tier rate-limit safety). The matching engine has no rate limit. 500 ms produces ~40 orders / refresh of visible turnover without flickering; 250 ms started to overlap with Streamlit's full-page rerender on this machine. See `dashboard/pages/1_matching_engine.py:22-23`.

14. **Trade write batching: per-submit `executeBatch()`.** `PostgresTradeWriter.writeAll(Collection<Trade>)` does a single `addBatch` loop and one `executeBatch` per submit. A single submit can produce multiple fills if it sweeps several price levels; batching collapses those into one round-trip without introducing a queue or a writer thread. The `OrderJournal` is one row per submit, so it stays a single `executeUpdate`. See `matching-engine/.../persistence/PostgresTradeWriter.java`.

## Where things live

| Concern | Path |
|---|---|
| Plan artifact | `~/.claude/plans/lets-build-the-matching-snug-oasis.md` |
| Engine entrypoint | `matching-engine/src/main/java/com/portfolio/matching/App.java` |
| Order book DS&A core | `matching-engine/.../book/OrderBook.java` |
| Price-level FIFO | `matching-engine/.../book/PriceLevel.java` |
| Submit / log / journal funnel | `matching-engine/.../engine/Engine.java` |
| HTTP routes | `matching-engine/.../api/HttpServer.java` |
| In-memory recent-trades log | `matching-engine/.../api/TradeLog.java` |
| Order generator | `matching-engine/.../sim/SyntheticOrderGenerator.java` |
| Hikari pool + JDBC URL parser | `matching-engine/.../persistence/Db.java` |
| Journal contract | `matching-engine/.../persistence/OrderJournal.java` |
| Journal Postgres impl | `matching-engine/.../persistence/PostgresOrderJournal.java` |
| Trade writer Postgres impl | `matching-engine/.../persistence/PostgresTradeWriter.java` |
| Per-second snapshot writer | `matching-engine/.../persistence/SnapshotWriter.java` |
| Submission event record | `matching-engine/.../persistence/OrderEvent.java` |
| Env-var parser | `matching-engine/.../config/Config.java` |
| Schema (appended) | `sql/schema.sql:20-61` |
| Compose wiring | `docker-compose.yml:44-58` |
| Env example | `.env.example:10-14` |
| Multi-stage Dockerfile | `matching-engine/Dockerfile` |
| Dashboard page 1 (Finnhub) | `dashboard/app.py` |
| Dashboard page 2 (matching engine) | `dashboard/pages/1_matching_engine.py` |
| Dashboard shared helpers | `dashboard/_shared.py` |
| JUnit tests (book) | `matching-engine/src/test/java/.../book/OrderBookTest.java`, `PriceLevelTest.java` |
| JUnit test (generator) | `matching-engine/src/test/java/.../sim/SyntheticOrderGeneratorTest.java` |
| Python E2E test | `tests/test_matching_engine.py` |
| Shared test helpers | `tests/conftest.py` |

## Current state: what's verified

- `cd matching-engine && mvn test` → 25/25 green (OrderBookTest 18, PriceLevelTest 5, SyntheticOrderGeneratorTest 2).
- `pytest -v` (from repo root) → 21/21 green across all three test files. The matching-engine E2E suite spins both `goldman-porfolio-matching-engine:latest` and Postgres on a shared docker network via testcontainers; no mocks.
- `ruff check .` clean.
- `docker compose build matching-engine` produces a 473 MB image (Corretto 17 alpine on ARM64).
- `docker compose up -d` brings all five services healthy. The matching-engine container produces visible book activity within a second of startup; the dashboard renders the multi-page UI; the matching-engine page reflects live book state at 2 Hz.
- `curl localhost:8080/health` → `{"status":"ok"}`. `/book/SYNTH1/top` returns a non-null spread within seconds.
- `psql ... -c "SELECT COUNT(*) FROM me_trades"` and `me_orders` and `me_book_snapshots` all return growing counts inside the live stack.

Not verified:
- AWS Lightsail deployment of the Java service — same status as the Finnhub stack (`SPEC.md §11` still applies).
- Long-run memory behavior. `me_book_snapshots` grows monotonically at 1 row/sec/symbol; flagged in review but not pruned.

## How to run / reproduce

From `/Users/samshulman/Coding/My-Software-Projects/goldman-porfolio/`.

```bash
# Java tests, standalone
cd matching-engine && mvn test

# Build the fat jar locally (produces target/matching-engine-0.1.0-shaded.jar)
mvn -DskipTests package

# Run the engine outside Docker on a non-default port
HTTP_PORT=18080 java -jar matching-engine/target/matching-engine-0.1.0-shaded.jar
# (No DATABASE_URL set → journals/writers use NOOP impls; in-memory only.)

# Build the docker image
docker compose build matching-engine

# Bring up the whole stack (needs port 8080 free — see gotcha 1)
docker compose up -d

# Run the Python E2E suite (requires the engine image to be built first)
.venv/bin/python -m pytest tests/test_matching_engine.py -v
```

The matching-engine page is reachable at `http://localhost:8501/matching_engine` once the dashboard is up. Engine API is at `http://localhost:8080`.

## Gotchas and footguns

1. **Host port 8080 was occupied by the user's `mongodb-benchmarking-api-1` container.** The matching-engine compose entry maps `8080:8080`. For `docker compose up` to succeed, that container had to be `docker stop`ped. It is reversible (`docker start mongodb-benchmarking-api-1`). The session-summary from the local-stack build noted the same pattern for port 8000.

2. **`eclipse-temurin:17-jre-alpine` has no ARM64 manifest.** First Dockerfile attempt failed with `no match for platform in manifest: not found` on Apple Silicon. Switched to `eclipse-temurin:17-jre-jammy` (382 MB), then to `amazoncorretto:17-alpine` (473 MB — counterintuitively larger). Final image is bigger than the `<200 MB` self-imposed target in the plan, but acceptable; the Python service images in this repo are similarly sized.

3. **`maven-shade-plugin` `finalName` override broke the "replace original artifact" step.** Initial pom config set `<finalName>${project.artifactId}-${project.version}-shaded</finalName>`, which caused the plugin to fail with `Could not replace original artifact with shaded artifact`. Fix: switch to `<shadedArtifactAttached>true</shadedArtifactAttached>` with `<shadedClassifierName>shaded</shadedClassifierName>`. Both the unshaded main jar and the shaded jar now coexist in `target/`; the Dockerfile copies the `-shaded` one.

4. **Postgres URL format mismatch.** psycopg accepts `postgresql://app:app@postgres:5432/market`; JDBC needs `jdbc:postgresql://...` and credentials separated. `Db.java` parses the libpq-style URL via `URI.create` and reformats. Keep the env var the same shape across the Python and Java services — do not split into two env vars.

5. **`use_container_width` deprecation warning floods dashboard logs.** Streamlit 1.40+ deprecates this parameter in favor of `width='stretch'`. The existing Finnhub page uses it; the new matching-engine page does too. Not changed this session. Warning is harmless but the logs are noisy.

6. **Streamlit page imports use `from _shared import ...`, NOT `from dashboard._shared import ...`.** Streamlit puts the script's directory on `sys.path`, not its parent. The `dashboard/` directory is not a package (no `__init__.py`), so `from _shared` is the right form from both `dashboard/app.py` and `dashboard/pages/*.py`. `ruff --fix` auto-reorders the import block; do not let an "organize imports" pass quietly switch to `from dashboard._shared`.

7. **`matching-engine/target/` was accidentally committed in `a783b3c`.** The session's first commit included build artifacts (class files, jars, surefire reports — 40 files, ~10 MB) because there was no `.gitignore` entry for them yet. Cleaned up in the review pass: `.gitignore` adds `matching-engine/target/` and `*.class`; `git rm -r --cached matching-engine/target` removed the tracked files. This cleanup is currently uncommitted.

8. **The `OrderBook.match` inline-unlink trap.** The original hand-rolled unlink in `match()` carried a fragile invariant: `recordFill` debits `totalQuantity` by `fillQty`, then if the maker is fully consumed, `unlink` would *also* debit by the maker's remaining (which is 0 at that point). The hand-rolled code was avoiding a phantom double-decrement that wasn't actually possible. Code review flagged this; the cleanup pass replaced the 14-line inline unlink with `level.unlink(maker); ordersById.remove(maker.id());`. If you ever change `decreaseQuantity` to happen *after* the if-check, this assumption breaks.

9. **`OrderBook.pickRestingOrderId(int randomIndex)` is O(n).** It iterates `ordersById.keySet()` to find the i-th element. Review flagged it as contradicting the "O(1) cancel" design claim. The claim is technically intact (the cancel itself is O(1) via the hashmap), but selecting *which* order to cancel is linear. Fix would require a parallel `ArrayList<Long>` with swap-remove indices — three data structures total. Deliberately skipped at this scale (~5 cancels / sec / symbol, ~200 resting orders) but worth doing if anyone bumps the generator rate.

10. **The `OrderJournal` Javadoc once over-promised.** The original interface comment said "Implementations should be cheap and non-blocking from the engine's perspective; a database hiccup must not stall matching." The actual `PostgresOrderJournal.record` is fully synchronous and *does* block on Postgres. Cleanup pass relaxed the Javadoc to match the impl: "Persistence is best-effort: the engine calls through synchronously, but a DB hiccup logs a warning rather than propagating." A future async writer thread is the path if this becomes a real bottleneck.

11. **`AtomicLong` inside a `synchronized` class is a smell.** Code review caught this. Anyone reading `AtomicLong nextOrderId` would assume there is lock-free concurrency intent. Plain `long nextOrderId++` after cleanup. Lesson: pick the synchronization primitive that matches the design, not the most thread-safe-looking option.

12. **`tests/conftest.py` houses helpers, not just fixtures.** The shared `apply_schema(container)` and `normalize_pg_url(url)` helpers live in `tests/conftest.py` and are imported as `from tests.conftest import apply_schema`. This is slightly off-convention (`conftest.py` is normally for fixtures) but pytest treats it as a regular module and the project already has `pythonpath = ["."]` configured. If you add real pytest fixtures later, they go in the same file.

13. **`Db.java` accepts the libpq URL shape only.** If you change `.env.example`'s `DATABASE_URL` to a JDBC-style URL, the Java service will fail at startup because `URI.create("jdbc:postgresql://...")` parses the `jdbc:` scheme as the URI scheme and the rest of the parse comes out wrong. Keep the env var in libpq form (`postgresql://user:pass@host:port/db`); the Java service does the conversion internally.

14. **`prepareThreshold=1` only helps when the same connection sees the same SQL more than once.** Hikari's pool returns the same physical connection across many checkouts, so this is a real win for the engine's hot-path SQL. If you ever shrink the pool to 1 connection or stop reusing connections, the threshold helps less. The setting is at `Db.java:42-44`.

15. **`testcontainers` python client uses `postgresql+psycopg2` in connection URLs.** Stripping it is in `tests/conftest.py:normalize_pg_url`. Three places previously did this manually; all three now call the helper.

16. **`docker compose build matching-engine` from a cold cache takes ~25 s (dependency resolution dominates).** Subsequent rebuilds with code-only changes finish in ~3 s thanks to the `dependency:go-offline` layer ordering. Do not collapse the pom and src copies into one layer; the cache stratification is intentional.

17. **The Streamlit matching-engine page makes 3 HTTP calls per refresh.** Top, depth, trades. At 2 Hz that is 6 GETs/sec to the engine, which is trivial in absolute terms but worth knowing if you ever shrink the refresh interval further. A single `/book/{symbol}?include=trades` endpoint would collapse them, but the engine API would have to change.

## What's left to ship

Must-have (carried over from previous session, not specific to this matching engine work):
1. `.github/workflows/ci.yml` — needs to run both `pytest` and `mvn test` now, and `docker compose build` for all four services.
2. README rewrite — needs a matching-engine section, depth-chart screenshot, and an architecture diagram showing both subsystems.
3. AWS Lightsail Container Service deployment for all four services.
4. `git remote add origin ...` and push.

Specific to the matching engine:
5. **Commit the review-cleanup changes** (54 files staged, currently uncommitted). The cleanup includes the `target/` removal, `OrderBook.java` and `TradeLog.java` simplifications, the new `OrderEvent` record, `tests/conftest.py`, `dashboard/_shared.py`, the `prepareThreshold=1` setting, and the WHAT-comment trim in `TradeLog` and `Engine`.
6. Snapshot retention sweeper for `me_book_snapshots` if the stack runs for more than a few days. ~170 k rows/day on a Lightsail Nano will eventually matter.

Nice-to-have:
- IOC and FOK order types. The plan called these out as a "modest extra work" follow-up.
- A manual-order submission form on the matching-engine Streamlit page (would let a reviewer interact with the book live, not just watch).
- Async write path for `OrderJournal` and `TradeWriter` (queue + drain thread) if the engine's tick cadence is ever pushed below 50 ms.
- Lookup-table for `pickRestingOrderId` if generator load increases.

## Branch state / commits

Branch: `main`. Two commits added this session — one from the build, one from the cleanup (uncommitted as of this writing).

```
a783b3c feat(matching-engine): add Java limit-order-book service with synthetic order flow
4462968 docs: add session summary for the 2026-05-24 local-stack build  (previous session)
```

Uncommitted: 54 files. Of those, 40 are `D ` deletions of the accidentally-committed `target/` artifacts, and the remaining 14 are the review-cleanup edits across `.gitignore`, `dashboard/`, `tests/`, and the Java sources listed in decision 8-11. No remote is configured; nothing has been pushed.

The plan-mode artifact at `~/.claude/plans/lets-build-the-matching-snug-oasis.md` was approved and remains in place for reference.

## Known unknowns

- Whether the testcontainers approach in `tests/test_matching_engine.py` will work cleanly in GitHub Actions. The local run depends on a docker-in-docker arrangement that CI usually provides via the `docker` service container, but the matching-engine image needs to be built in the same CI job before pytest runs.
- Whether the Lightsail Nano plan has enough RAM to run both the Python services and the JVM service simultaneously. The matching-engine container at startup is ~150 MB resident; with the three Python services and Postgres, this is closer to the Lightsail Nano ceiling than the previous (Python-only) stack.
- Whether reviewers actually look at the JUnit test output. The DS&A coverage in `OrderBookTest` (price-time priority, partial fills, multi-level sweep, scale-equivalent BigDecimal coalescing) is more impressive in code than in a passing-test list; a README snippet quoting one of the more interesting tests would help surface it.
- Whether the synthetic generator's 70/20/10 split produces enough alert-worthy activity to justify forcing screenshots without further tuning. The current parameters yield a book that turns over briskly but doesn't move dramatically. A higher market-order percentage would produce more obvious sweeps for a demo.
