CREATE TABLE dashboard.usage_daily (
    bucket_start timestamptz NOT NULL,
    agent_id text NOT NULL DEFAULT '',
    session_id text NOT NULL DEFAULT '',
    model text NOT NULL DEFAULT '',
    uncached_input_tokens bigint NOT NULL,
    cache_creation_1h_input_tokens bigint NOT NULL,
    cache_creation_5m_input_tokens bigint NOT NULL,
    cache_read_input_tokens bigint NOT NULL,
    output_tokens bigint NOT NULL,
    total_tokens bigint NOT NULL,
    requests bigint NOT NULL,
    web_search_requests bigint NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (bucket_start, agent_id, session_id, model)
);

CREATE INDEX usage_daily_session_idx ON dashboard.usage_daily (session_id);

CREATE TABLE dashboard.cost_daily (
    bucket_start timestamptz NOT NULL,
    agent_id text NOT NULL DEFAULT '',
    session_id text NOT NULL DEFAULT '',
    model text NOT NULL DEFAULT '',
    cost_type text NOT NULL DEFAULT '',
    token_type text NOT NULL DEFAULT '',
    amount_cents numeric(24, 6) NOT NULL,
    list_amount_cents numeric(24, 6),
    currency text NOT NULL,
    requests bigint NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (bucket_start, agent_id, session_id, model, cost_type, token_type)
);

CREATE INDEX cost_daily_session_idx ON dashboard.cost_daily (session_id);

CREATE TABLE dashboard.ingest_run (
    run_id bigserial PRIMARY KEY,
    finished_at timestamptz NOT NULL DEFAULT now(),
    window_start timestamptz NOT NULL,
    window_end timestamptz NOT NULL,
    usage_refreshed_at timestamptz,
    cost_refreshed_at timestamptz
);
