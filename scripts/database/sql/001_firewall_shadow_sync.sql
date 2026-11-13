\set ON_ERROR_STOP on

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $$
BEGIN
    IF current_database() <> 'sentinel'
       OR inet_server_port() IS DISTINCT FROM 5433
       OR replace(current_setting('data_directory'), chr(92), '/') <> 'E:/Sentinel/PostgreSQL/data'
    THEN
        RAISE EXCEPTION 'Instancia divergente. Migracao cancelada.';
    END IF;
END
$$;

SET LOCAL ROLE sentinel_owner;

CREATE TABLE operacional.sincronizacoes (
    fonte varchar(40) PRIMARY KEY CHECK (fonte = 'firewalls'),
    coleta_publicada_em timestamptz NOT NULL,
    conteudo_sha256 varchar(64) NOT NULL CHECK (conteudo_sha256 ~ '^[0-9a-f]{64}$'),
    sincronizado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE operacional.firewalls
    ADD COLUMN presente_no_snapshot boolean NOT NULL DEFAULT true,
    ADD COLUMN ultima_verificacao timestamptz,
    ADD COLUMN status varchar(120),
    ADD COLUMN status_disponibilidade varchar(120),
    ADD COLUMN licencas_informadas boolean NOT NULL DEFAULT false;

ALTER TABLE operacional.licencas_firewall
    ADD COLUMN presente_no_snapshot boolean NOT NULL DEFAULT true,
    ADD COLUMN dados_anteriores boolean NOT NULL DEFAULT false,
    ADD COLUMN ultima_coleta_valida timestamptz,
    ADD COLUMN status_ultima_coleta_valida varchar(120);

CREATE UNIQUE INDEX licencas_firewall_origem_unique
    ON operacional.licencas_firewall (firewall_id, nome, tipo) NULLS NOT DISTINCT;

GRANT SELECT ON operacional.sincronizacoes TO sentinel_reader;
GRANT SELECT, INSERT, UPDATE ON operacional.sincronizacoes TO sentinel_collector;

COMMIT;
