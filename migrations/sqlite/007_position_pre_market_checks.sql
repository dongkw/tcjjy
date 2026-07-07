CREATE TABLE IF NOT EXISTS position_pre_market_checks (
    check_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    trade_date TEXT,
    check_time TEXT NOT NULL,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    rule_code TEXT NOT NULL,
    message TEXT NOT NULL,
    current_price NUMERIC,
    reference_price NUMERIC,
    position_pct NUMERIC,
    available_quantity INTEGER,
    locked_quantity INTEGER,
    payload_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_position_pre_market_checks_date
ON position_pre_market_checks (trade_date, check_time);

CREATE INDEX IF NOT EXISTS idx_position_pre_market_checks_account_symbol
ON position_pre_market_checks (account_id, symbol);
