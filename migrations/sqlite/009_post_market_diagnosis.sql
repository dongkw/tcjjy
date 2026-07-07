CREATE TABLE IF NOT EXISTS post_market_diagnosis_runs (
    run_id TEXT PRIMARY KEY,
    trade_date TEXT,
    next_trade_date TEXT,
    source_tabs_json TEXT,
    include_positions INTEGER NOT NULL DEFAULT 1,
    total_count INTEGER,
    success_count INTEGER,
    failed_count INTEGER,
    position_risk_count INTEGER,
    buy_candidate_count INTEGER,
    watch_count INTEGER,
    data_gap_count INTEGER,
    created_at TEXT NOT NULL,
    params_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_post_market_diagnosis_runs_created
ON post_market_diagnosis_runs (created_at);

CREATE TABLE IF NOT EXISTS post_market_diagnosis_results (
    result_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    source_type TEXT,
    category TEXT NOT NULL,
    priority TEXT NOT NULL,
    score NUMERIC,
    price NUMERIC,
    pct_change NUMERIC,
    trade_date TEXT,
    matched_rules_json TEXT,
    warnings_json TEXT,
    summary TEXT,
    created_at TEXT NOT NULL,
    payload_json TEXT,
    FOREIGN KEY (run_id) REFERENCES post_market_diagnosis_runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_post_market_diagnosis_results_run
ON post_market_diagnosis_results (run_id, category, priority);

CREATE TABLE IF NOT EXISTS next_day_watch_items (
    item_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    source_type TEXT,
    category TEXT NOT NULL,
    priority TEXT NOT NULL,
    reason TEXT,
    current_price NUMERIC,
    reference_price NUMERIC,
    trade_date TEXT,
    next_trade_date TEXT,
    review_status TEXT NOT NULL DEFAULT 'UNREVIEWED',
    review_action TEXT,
    reviewed_at TEXT,
    review_note TEXT,
    decision_id TEXT,
    created_at TEXT NOT NULL,
    payload_json TEXT,
    FOREIGN KEY (run_id) REFERENCES post_market_diagnosis_runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_next_day_watch_items_run
ON next_day_watch_items (run_id, priority, category);

CREATE INDEX IF NOT EXISTS idx_next_day_watch_items_review
ON next_day_watch_items (next_trade_date, review_status);
