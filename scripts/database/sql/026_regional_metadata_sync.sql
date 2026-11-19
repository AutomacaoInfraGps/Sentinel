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
ALTER TABLE operacional.metadados_regionais
    ADD COLUMN presente_na_captura boolean NOT NULL DEFAULT true,
    ADD COLUMN atualizado_em timestamptz;
CREATE TABLE operacional.sincronizacoes_metadados_regionais (
    fonte_id varchar(120) PRIMARY KEY REFERENCES operacional.fontes_metadados_regionais(id) ON DELETE RESTRICT,
    capturado_em timestamptz NOT NULL,
    publicacao_textual varchar(80) NOT NULL,
    arquivo_origem_sha256 varchar(64) NOT NULL CHECK (arquivo_origem_sha256 ~ '^[0-9a-f]{64}$'),
    metadados_sha256 varchar(64) NOT NULL CHECK (metadados_sha256 ~ '^[0-9a-f]{64}$'),
    digest_carga varchar(64) NOT NULL CHECK (digest_carga ~ '^[0-9a-f]{64}$'),
    regionais integer NOT NULL CHECK (regionais > 0),
    sincronizado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
REVOKE ALL ON operacional.sincronizacoes_metadados_regionais FROM PUBLIC, sentinel_reader, sentinel_api;
GRANT SELECT ON operacional.sincronizacoes_metadados_regionais TO sentinel_regionais_metadados_reader;
GRANT SELECT, INSERT, UPDATE ON operacional.sincronizacoes_metadados_regionais TO sentinel_collector;
GRANT UPDATE ON operacional.metadados_regionais TO sentinel_collector;
COMMIT;
