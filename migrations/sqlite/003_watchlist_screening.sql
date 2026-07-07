CREATE TABLE IF NOT EXISTS watchlist_screen_runs (
    run_id TEXT PRIMARY KEY,
    tab_id TEXT,
    tab_name TEXT,
    screen_type TEXT NOT NULL DEFAULT 'pre_market',
    trade_date TEXT,
    total_count INTEGER,
    candidate_count INTEGER,
    watch_count INTEGER,
    risk_count INTEGER,
    data_gap_count INTEGER,
    created_at TEXT,
    params_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_watchlist_screen_runs_created ON watchlist_screen_runs (created_at);

CREATE TABLE IF NOT EXISTS watchlist_screen_results (
    result_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    category TEXT,
    score NUMERIC,
    price NUMERIC,
    pct_change NUMERIC,
    pe_ttm NUMERIC,
    pb NUMERIC,
    ma20 NUMERIC,
    ma60 NUMERIC,
    change_20d_pct NUMERIC,
    trade_date TEXT,
    is_position INTEGER NOT NULL DEFAULT 0,
    matched_rules_json TEXT,
    warnings_json TEXT,
    summary TEXT,
    created_at TEXT,
    FOREIGN KEY (run_id) REFERENCES watchlist_screen_runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_watchlist_screen_results_run ON watchlist_screen_results (run_id, category, score);
CREATE INDEX IF NOT EXISTS idx_watchlist_screen_results_symbol ON watchlist_screen_results (symbol);
