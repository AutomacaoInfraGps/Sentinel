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
ALTER TABLE operacional.observacoes_replicacao_ad ADD COLUMN presente_na_fonte boolean NOT NULL DEFAULT true;
ALTER TABLE operacional.erros_operacionais_replicacao_ad ADD COLUMN presente_na_fonte boolean NOT NULL DEFAULT true;
-- Order is mutable display position, not controller identity. Keep the existing unique index too.
ALTER TABLE operacional.observacoes_replicacao_ad DROP CONSTRAINT observacoes_replicacao_ad_pkey;
ALTER TABLE operacional.observacoes_replicacao_ad ADD PRIMARY KEY (fonte_id,nome_identidade,secao);
CREATE TABLE operacional.sincronizacoes_replicacao_ad (
    fonte_id varchar(120) PRIMARY KEY REFERENCES operacional.fontes_replicacao_ad(id) ON DELETE RESTRICT,
    lido_em timestamptz NOT NULL,
    conteudo_sha256 varchar(64) NOT NULL CHECK (conteudo_sha256 ~ '^[0-9a-f]{64}$'),
    origem_config_sha256 varchar(64) NOT NULL CHECK (origem_config_sha256 ~ '^[0-9a-f]{64}$'),
    sincronizado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
REVOKE ALL ON operacional.sincronizacoes_replicacao_ad FROM PUBLIC, sentinel_reader, sentinel_api;
GRANT SELECT ON operacional.sincronizacoes_replicacao_ad TO sentinel_replicacao_reader;
GRANT SELECT, INSERT, UPDATE ON operacional.sincronizacoes_replicacao_ad TO sentinel_collector;
GRANT UPDATE ON operacional.fontes_replicacao_ad, operacional.observacoes_replicacao_ad,
    operacional.erros_operacionais_replicacao_ad TO sentinel_collector;
COMMIT;
