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
