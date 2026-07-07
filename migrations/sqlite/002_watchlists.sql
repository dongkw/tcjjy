CREATE TABLE IF NOT EXISTS watchlist_tabs (
    tab_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    tab_type TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 100,
    is_default INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT,
    updated_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_watchlist_tabs_name ON watchlist_tabs (name);
CREATE INDEX IF NOT EXISTS idx_watchlist_tabs_active_sort ON watchlist_tabs (is_active, sort_order);

CREATE TABLE IF NOT EXISTS watchlist_items (
    item_id TEXT PRIMARY KEY,
    tab_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    asset_type TEXT NOT NULL DEFAULT 'stock',
    note TEXT,
    created_at TEXT,
    updated_at TEXT,
    payload_json TEXT,
    FOREIGN KEY (tab_id) REFERENCES watchlist_tabs(tab_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_watchlist_items_tab_symbol ON watchlist_items (tab_id, symbol);
CREATE INDEX IF NOT EXISTS idx_watchlist_items_symbol ON watchlist_items (symbol);

CREATE TABLE IF NOT EXISTS market_quotes (
    symbol TEXT PRIMARY KEY,
    name TEXT,
    exchange TEXT,
    asset_type TEXT NOT NULL DEFAULT 'stock',
    trade_date TEXT,
    quote_time TEXT,
    price NUMERIC,
    pct_change NUMERIC,
    pe_ttm NUMERIC,
    pb NUMERIC,
    market_cap_yuan NUMERIC,
    ma20 NUMERIC,
    ma60 NUMERIC,
    change_20d_pct NUMERIC,
    source TEXT,
    source_path TEXT,
    updated_at TEXT,
    payload_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_market_quotes_name ON market_quotes (name);
CREATE INDEX IF NOT EXISTS idx_market_quotes_trade_date ON market_quotes (trade_date);
