CREATE TABLE IF NOT EXISTS documents (
    id uuid PRIMARY KEY,
    scope_id text NOT NULL CHECK (length(btrim(scope_id)) > 0),
    source_key text NOT NULL CHECK (length(btrim(source_key)) > 0),
    version integer NOT NULL CHECK (version > 0),
    content_hash char(64) NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    title text NOT NULL CHECK (length(btrim(title)) > 0),
    body text NOT NULL CHECK (length(btrim(body)) > 0),
    symbol varchar(6),
    kind text NOT NULL CHECK (kind IN ('announcement', 'research', 'note')),
    mode text NOT NULL CHECK (mode IN ('fixture', 'imported')),
    source_name text NOT NULL CHECK (length(btrim(source_name)) > 0),
    source_url text CHECK (source_url IS NULL OR source_url ~ '^https?://'),
    available_at timestamptz NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,
    CONSTRAINT documents_source_version UNIQUE (scope_id, source_key, version),
    CONSTRAINT documents_source_hash UNIQUE (scope_id, source_key, content_hash),
    CHECK (symbol IS NULL OR symbol ~ '^(000|001|002|003|600|601|603|605)[0-9]{3}$')
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES documents(id),
    chunk_no integer NOT NULL CHECK (chunk_no >= 0),
    start_char integer NOT NULL CHECK (start_char >= 0),
    end_char integer NOT NULL CHECK (end_char > start_char),
    text text NOT NULL,
    token_count integer NOT NULL CHECK (token_count > 0),
    embedding vector(512) NOT NULL,
    embedding_model text NOT NULL,
    embedding_revision text NOT NULL,
    chunking_version text NOT NULL,
    CONSTRAINT document_chunks_profile_number UNIQUE (
        document_id, embedding_model, embedding_revision, chunking_version, chunk_no
    ),
    CHECK (char_length(text) = end_char - start_char)
);

CREATE INDEX IF NOT EXISTS documents_scope_source_available
    ON documents (scope_id, source_key, available_at DESC, version DESC)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS documents_scope_symbol_kind
    ON documents (scope_id, symbol, kind) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS document_chunks_profile
    ON document_chunks (embedding_model, embedding_revision, chunking_version, document_id);

CREATE TABLE IF NOT EXISTS retrieval_evaluations (
    id uuid PRIMARY KEY,
    scope_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    result jsonb NOT NULL
);

INSERT INTO schema_migrations (version) VALUES (2)
ON CONFLICT (version) DO NOTHING;
