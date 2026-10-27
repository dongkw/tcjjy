CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS watchlist (
    symbol varchar(6) PRIMARY KEY,
    name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (symbol ~ '^(000|001|002|003|600|601|603|605)[0-9]{3}$')
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id uuid PRIMARY KEY,
    symbol varchar(6) NOT NULL,
    name text NOT NULL,
    mode text NOT NULL CHECK (mode IN ('live', 'fixture')),
    source text NOT NULL,
    adjustment text NOT NULL CHECK (adjustment IN ('qfq', 'none')),
    fetched_at timestamptz NOT NULL,
    first_trade_date date NOT NULL,
    last_trade_date date NOT NULL,
    bar_count integer NOT NULL CHECK (bar_count > 0),
    CHECK (symbol ~ '^(000|001|002|003|600|601|603|605)[0-9]{3}$'),
    CHECK (first_trade_date <= last_trade_date)
);

CREATE TABLE IF NOT EXISTS daily_bars (
    snapshot_id uuid NOT NULL REFERENCES market_snapshots(id),
    trade_date date NOT NULL,
    open numeric(24, 8) NOT NULL CHECK (open > 0),
    high numeric(24, 8) NOT NULL CHECK (high > 0),
    low numeric(24, 8) NOT NULL CHECK (low > 0),
    close numeric(24, 8) NOT NULL CHECK (close > 0),
    volume numeric(28, 4) CHECK (volume >= 0),
    amount numeric(28, 4) CHECK (amount >= 0),
    PRIMARY KEY (snapshot_id, trade_date),
    CHECK (low <= open AND low <= close AND high >= open AND high >= close AND high >= low)
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id uuid PRIMARY KEY,
    snapshot_id uuid NOT NULL REFERENCES market_snapshots(id),
    strategy_id text NOT NULL,
    strategy_version text NOT NULL,
    status text NOT NULL CHECK (status IN ('PASS', 'WATCH', 'BLOCKED')),
    summary text NOT NULL,
    missing_fields text[] NOT NULL DEFAULT '{}',
    indicators jsonb NOT NULL CHECK (jsonb_typeof(indicators) = 'object'),
    rules jsonb NOT NULL CHECK (jsonb_typeof(rules) = 'array'),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS market_snapshots_symbol_mode_time
    ON market_snapshots (symbol, mode, fetched_at DESC);
CREATE INDEX IF NOT EXISTS analysis_runs_created_at
    ON analysis_runs (created_at DESC);

INSERT INTO watchlist (symbol, name) VALUES
    ('601138', '工业富联'),
    ('600398', '海澜之家'),
    ('000969', '安泰科技')
ON CONFLICT (symbol) DO NOTHING;

INSERT INTO schema_migrations (version) VALUES (1)
ON CONFLICT (version) DO NOTHING;
