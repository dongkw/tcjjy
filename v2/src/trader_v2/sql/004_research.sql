CREATE TABLE IF NOT EXISTS research_sessions (
    id uuid PRIMARY KEY,
    scope_id text NOT NULL,
    symbol varchar(6) NOT NULL,
    question text NOT NULL,
    mode text NOT NULL CHECK (mode IN ('fixture', 'imported')),
    as_of timestamptz NOT NULL,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'completed')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS research_searches (
    id uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES research_sessions(id),
    query text NOT NULL,
    top_k integer NOT NULL,
    min_score double precision NOT NULL,
    model_id text NOT NULL,
    model_revision text NOT NULL,
    chunking_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS research_evidence (
    id uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES research_sessions(id),
    search_id uuid NOT NULL REFERENCES research_searches(id),
    chunk_id uuid NOT NULL REFERENCES document_chunks(id),
    score double precision NOT NULL,
    read_at timestamptz,
    UNIQUE (search_id, chunk_id)
);

CREATE TABLE IF NOT EXISTS research_reports (
    id uuid PRIMARY KEY,
    session_id uuid NOT NULL UNIQUE REFERENCES research_sessions(id),
    scope_id text NOT NULL,
    symbol varchar(6) NOT NULL,
    mode text NOT NULL CHECK (mode IN ('fixture', 'imported')),
    as_of timestamptz NOT NULL,
    title text NOT NULL,
    summary text NOT NULL,
    facts jsonb NOT NULL,
    inferences text[] NOT NULL,
    missing_information text[] NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS research_citations (
    report_id uuid NOT NULL REFERENCES research_reports(id),
    evidence_id uuid NOT NULL REFERENCES research_evidence(id),
    chunk_id uuid NOT NULL REFERENCES document_chunks(id),
    document_id uuid NOT NULL REFERENCES documents(id),
    source_key text NOT NULL,
    source_version integer NOT NULL,
    title text NOT NULL,
    source_name text NOT NULL,
    source_url text,
    available_at timestamptz NOT NULL,
    start_char integer NOT NULL,
    end_char integer NOT NULL,
    text text NOT NULL,
    PRIMARY KEY (report_id, evidence_id)
);

CREATE INDEX IF NOT EXISTS research_sessions_scope ON research_sessions(scope_id, created_at DESC);
CREATE INDEX IF NOT EXISTS research_reports_scope_symbol ON research_reports(scope_id, symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS research_evidence_session ON research_evidence(session_id);

INSERT INTO schema_migrations (version) VALUES (4) ON CONFLICT (version) DO NOTHING;
