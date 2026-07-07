ALTER TABLE watchlist_screen_results ADD COLUMN review_status TEXT NOT NULL DEFAULT 'UNREVIEWED';
ALTER TABLE watchlist_screen_results ADD COLUMN review_action TEXT;
ALTER TABLE watchlist_screen_results ADD COLUMN reviewed_at TEXT;
ALTER TABLE watchlist_screen_results ADD COLUMN review_note TEXT;

CREATE INDEX IF NOT EXISTS idx_watchlist_screen_results_review
ON watchlist_screen_results (run_id, review_status);
