CREATE TABLE IF NOT EXISTS agent_memory (
    id uuid PRIMARY KEY,
    scope_id text NOT NULL CHECK (scope_id ~ '^[A-Za-z0-9_.:-]{1,80}$'),
    revision integer NOT NULL CHECK (revision > 0),
    kind text NOT NULL CHECK (kind IN ('preference', 'pending', 'lesson')),
    symbol varchar(6) CHECK (symbol IS NULL OR symbol ~ '^(000|001|002|003|600|601|603|605)[0-9]{3}$'),
    content text NOT NULL CHECK (length(btrim(content)) BETWEEN 1 AND 1200),
    source_type text NOT NULL CHECK (source_type IN ('user_statement', 'research_report')),
    source_reference text NOT NULL CHECK (length(btrim(source_reference)) BETWEEN 1 AND 200),
    source_mode text CHECK (source_mode IS NULL OR source_mode IN ('fixture', 'imported')),
    epistemic_status text NOT NULL CHECK (epistemic_status IN ('user_asserted', 'provisional_lesson')),
    status text NOT NULL CHECK (status IN ('active', 'deactivated')),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    embedding vector(512) NOT NULL,
    embedding_model text NOT NULL,
    embedding_revision text NOT NULL,
    CHECK (expires_at > created_at),
    CHECK ((kind IN ('preference', 'pending') AND source_type = 'user_statement' AND epistemic_status = 'user_asserted')
        OR (kind = 'lesson' AND source_type = 'research_report' AND epistemic_status = 'provisional_lesson'))
);

ALTER TABLE agent_memory ADD COLUMN IF NOT EXISTS source_mode text
    CHECK (source_mode IS NULL OR source_mode IN ('fixture', 'imported'));

CREATE INDEX IF NOT EXISTS agent_memory_active_scope
    ON agent_memory (scope_id, symbol, kind, expires_at) WHERE status = 'active';

-- Immutable snapshots preserve revisions and deactivation history. The current
-- projection above is the only table considered by semantic recall.
CREATE TABLE IF NOT EXISTS agent_memory_versions (
    memory_id uuid NOT NULL REFERENCES agent_memory(id),
    revision integer NOT NULL CHECK (revision > 0),
    scope_id text NOT NULL,
    kind text NOT NULL,
    symbol varchar(6),
    content text NOT NULL,
    source_type text NOT NULL,
    source_reference text NOT NULL,
    source_mode text,
    epistemic_status text NOT NULL,
    status text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    embedding vector(512) NOT NULL,
    embedding_model text NOT NULL,
    embedding_revision text NOT NULL,
    PRIMARY KEY (memory_id, revision)
);

ALTER TABLE agent_memory_versions ADD COLUMN IF NOT EXISTS source_mode text;

INSERT INTO schema_migrations (version) VALUES (3)
ON CONFLICT (version) DO NOTHING;
