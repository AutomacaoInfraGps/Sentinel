\set ON_ERROR_STOP on

BEGIN;

SET LOCAL ROLE sofia_owner;

CREATE TABLE IF NOT EXISTS sofia.sofia_chat_history (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id text NOT NULL CHECK (length(session_id) BETWEEN 1 AND 128),
    message jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS sofia_chat_history_session_idx
    ON sofia.sofia_chat_history (session_id, id);

CREATE INDEX IF NOT EXISTS sofia_chat_history_created_idx
    ON sofia.sofia_chat_history (created_at);

INSERT INTO sofia.schema_migrations (version, description)
VALUES (5, 'postgres chat memory for n8n agent')
ON CONFLICT (version) DO NOTHING;

RESET ROLE;

REVOKE ALL ON sofia.sofia_chat_history FROM PUBLIC;
GRANT SELECT, INSERT, DELETE ON sofia.sofia_chat_history TO sofia_runtime;
GRANT USAGE, SELECT ON SEQUENCE sofia.sofia_chat_history_id_seq TO sofia_runtime;

COMMIT;
