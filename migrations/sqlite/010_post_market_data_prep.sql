CREATE TABLE IF NOT EXISTS post_market_data_prep_runs (
    run_id TEXT PRIMARY KEY,
    trade_date TEXT,
    source_tabs_json TEXT,
    include_positions INTEGER NOT NULL DEFAULT 1,
    total_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    position_sync_count INTEGER NOT NULL DEFAULT 0,
    account_sync_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    error_message TEXT,
    params_json TEXT,
    payload_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_post_market_data_prep_runs_started
ON post_market_data_prep_runs (started_at);

CREATE INDEX IF NOT EXISTS idx_post_market_data_prep_runs_trade_date
ON post_market_data_prep_runs (trade_date, status);

CREATE TABLE IF NOT EXISTS post_market_data_prep_items (
    item_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    source_type TEXT,
    status TEXT NOT NULL,
    trade_date TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    payload_json TEXT,
    FOREIGN KEY (run_id) REFERENCES post_market_data_prep_runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_post_market_data_prep_items_run
ON post_market_data_prep_items (run_id, status, symbol);
