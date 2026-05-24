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

-- Matching engine: standalone subsystem driven by a synthetic order generator.
-- Tables are prefixed me_ to isolate them from the Finnhub ingestion subsystem.
-- Order ids are assigned by the engine (not BIGSERIAL) so journal rows can be
-- written without a server round trip to fetch the id.

CREATE TABLE me_orders (
  id          BIGINT PRIMARY KEY,
  symbol      TEXT NOT NULL,
  side        TEXT NOT NULL,
  order_type  TEXT NOT NULL,
  price       NUMERIC(12,4),
  quantity    BIGINT NOT NULL,
  ts          TIMESTAMPTZ NOT NULL,
  remaining   BIGINT NOT NULL,
  resting     BOOLEAN NOT NULL
);
CREATE INDEX idx_me_orders_symbol_ts ON me_orders (symbol, ts DESC);

CREATE TABLE me_trades (
  id              BIGSERIAL PRIMARY KEY,
  symbol          TEXT NOT NULL,
  maker_order_id  BIGINT NOT NULL,
  taker_order_id  BIGINT NOT NULL,
  price           NUMERIC(12,4) NOT NULL,
  quantity        BIGINT NOT NULL,
  ts              TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_me_trades_symbol_ts ON me_trades (symbol, ts DESC);

CREATE TABLE me_book_snapshots (
  id                BIGSERIAL PRIMARY KEY,
  symbol            TEXT NOT NULL,
  ts                TIMESTAMPTZ NOT NULL,
  best_bid          NUMERIC(12,4),
  bid_size          BIGINT,
  best_ask          NUMERIC(12,4),
  ask_size          BIGINT,
  spread            NUMERIC(12,4),
  last_trade_price  NUMERIC(12,4)
);
CREATE INDEX idx_me_book_snapshots_symbol_ts ON me_book_snapshots (symbol, ts DESC);
