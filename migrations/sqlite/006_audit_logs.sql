CREATE TABLE IF NOT EXISTS audit_logs (
    audit_id TEXT PRIMARY KEY,
    account_id TEXT,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    before_value_json TEXT,
    after_value_json TEXT,
    reason TEXT,
    operator TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_target ON audit_logs (target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_account_time ON audit_logs (account_id, created_at);
