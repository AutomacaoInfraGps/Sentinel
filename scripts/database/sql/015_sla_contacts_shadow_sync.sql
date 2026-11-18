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
ALTER TABLE operacional.regionais_contatos_sla ADD COLUMN presente_na_fonte boolean NOT NULL DEFAULT true;
ALTER TABLE operacional.contatos_regionais_sla ADD COLUMN presente_na_fonte boolean NOT NULL DEFAULT true;
CREATE TABLE operacional.sincronizacoes_contatos_sla (
    fonte_id varchar(120) PRIMARY KEY REFERENCES operacional.fontes_contatos_sla(id) ON DELETE RESTRICT,
    lido_em timestamptz NOT NULL,
    conteudo_sha256 varchar(64) NOT NULL CHECK (conteudo_sha256 ~ '^[0-9a-f]{64}$'),
    origem_config_sha256 varchar(64) NOT NULL CHECK (origem_config_sha256 ~ '^[0-9a-f]{64}$'),
    sincronizado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
REVOKE ALL ON operacional.sincronizacoes_contatos_sla FROM PUBLIC, sentinel_reader, sentinel_api;
GRANT SELECT ON operacional.sincronizacoes_contatos_sla TO sentinel_contatos_reader;
GRANT SELECT, INSERT, UPDATE ON operacional.sincronizacoes_contatos_sla TO sentinel_collector;
GRANT UPDATE ON operacional.fontes_contatos_sla, operacional.regionais_contatos_sla,
    operacional.contatos_regionais_sla TO sentinel_collector;
COMMIT;
