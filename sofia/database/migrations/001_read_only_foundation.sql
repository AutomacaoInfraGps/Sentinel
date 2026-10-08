\set ON_ERROR_STOP on

BEGIN;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;

CREATE SCHEMA IF NOT EXISTS sofia AUTHORIZATION sofia_owner;
REVOKE ALL ON SCHEMA sofia FROM PUBLIC;
GRANT USAGE ON SCHEMA sofia TO sofia_runtime;

SET LOCAL ROLE sofia_owner;

CREATE TABLE IF NOT EXISTS sofia.schema_migrations (
    version integer PRIMARY KEY,
    description text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS sofia.alert_snapshots (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source text NOT NULL CHECK (source ~ '^[a-z0-9._-]{1,50}$'),
    source_alert_id text NOT NULL CHECK (length(source_alert_id) BETWEEN 1 AND 200),
    severity text NOT NULL CHECK (severity IN ('critical', 'important', 'success', 'info')),
    title text NOT NULL CHECK (length(title) BETWEEN 1 AND 300),
    regional text CHECK (regional IS NULL OR length(regional) <= 120),
    device text CHECK (device IS NULL OR length(device) <= 200),
    occurred_at timestamptz,
    observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    active boolean NOT NULL DEFAULT true,
    content_sha256 char(64) NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    UNIQUE (source, source_alert_id)
);

CREATE INDEX IF NOT EXISTS alert_snapshots_active_idx
    ON sofia.alert_snapshots (active, severity, observed_at DESC);

CREATE TABLE IF NOT EXISTS sofia.audit_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    correlation_id uuid NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    actor_ref char(64) NOT NULL CHECK (actor_ref ~ '^[0-9a-f]{64}$'),
    channel text NOT NULL CHECK (channel IN ('sentinel', 'n8n', 'system')),
    event_type text NOT NULL CHECK (event_type ~ '^[a-z0-9._-]{1,100}$'),
    outcome text NOT NULL CHECK (outcome IN ('success', 'denied', 'failed', 'pending')),
    reason_code text CHECK (
        reason_code IS NULL OR reason_code ~ '^[a-z0-9._-]{1,100}$'
    )
);

CREATE INDEX IF NOT EXISTS audit_events_correlation_idx
    ON sofia.audit_events (correlation_id, occurred_at);
CREATE INDEX IF NOT EXISTS audit_events_occurred_idx
    ON sofia.audit_events (occurred_at DESC);

CREATE TABLE IF NOT EXISTS sofia.llm_interactions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    correlation_id uuid NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    actor_ref char(64) NOT NULL CHECK (actor_ref ~ '^[0-9a-f]{64}$'),
    channel text NOT NULL CHECK (channel IN ('sentinel', 'n8n')),
    provider text NOT NULL CHECK (length(provider) BETWEEN 1 AND 80),
    model text NOT NULL CHECK (length(model) BETWEEN 1 AND 120),
    normalized_intent text CHECK (
        normalized_intent IS NULL OR normalized_intent ~ '^[a-z0-9._-]{1,120}$'
    ),
    result text NOT NULL CHECK (result IN ('accepted', 'rejected', 'error', 'timeout')),
    input_characters integer NOT NULL CHECK (input_characters BETWEEN 0 AND 20000),
    output_characters integer NOT NULL CHECK (output_characters BETWEEN 0 AND 20000),
    latency_ms integer CHECK (latency_ms IS NULL OR latency_ms >= 0)
);

CREATE INDEX IF NOT EXISTS llm_interactions_correlation_idx
    ON sofia.llm_interactions (correlation_id, occurred_at);

INSERT INTO sofia.schema_migrations (version, description)
VALUES (1, 'read_only_foundation')
ON CONFLICT (version) DO NOTHING;

RESET ROLE;

REVOKE ALL ON ALL TABLES IN SCHEMA sofia FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA sofia FROM PUBLIC;

GRANT SELECT ON sofia.schema_migrations TO sofia_runtime;
GRANT SELECT, INSERT ON sofia.audit_events, sofia.llm_interactions TO sofia_runtime;
GRANT SELECT, INSERT ON sofia.alert_snapshots TO sofia_runtime;
GRANT UPDATE (
    severity,
    title,
    regional,
    device,
    occurred_at,
    observed_at,
    active,
    content_sha256
) ON sofia.alert_snapshots TO sofia_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA sofia TO sofia_runtime;

ALTER DEFAULT PRIVILEGES FOR ROLE sofia_owner IN SCHEMA sofia
    REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE sofia_owner IN SCHEMA sofia
    REVOKE ALL ON SEQUENCES FROM PUBLIC;

COMMIT;
