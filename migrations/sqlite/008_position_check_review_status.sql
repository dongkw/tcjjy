ALTER TABLE position_pre_market_checks ADD COLUMN review_status TEXT NOT NULL DEFAULT 'UNREVIEWED';
ALTER TABLE position_pre_market_checks ADD COLUMN review_action TEXT;
ALTER TABLE position_pre_market_checks ADD COLUMN reviewed_at TEXT;
ALTER TABLE position_pre_market_checks ADD COLUMN review_note TEXT;

CREATE INDEX IF NOT EXISTS idx_position_pre_market_checks_review
ON position_pre_market_checks (trade_date, review_status);
