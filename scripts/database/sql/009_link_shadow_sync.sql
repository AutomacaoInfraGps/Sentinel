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

ALTER TABLE operacional.links_internet
    ADD COLUMN atualizado_no_banco_em timestamptz,
    ADD COLUMN coleta_status_origem varchar(40) CHECK (
        coleta_status_origem IN ('sdwan_monitor', 'proxy_interface')),
    ALTER COLUMN arquivo_origem_sha256 DROP NOT NULL;

CREATE TABLE operacional.sincronizacoes_links (
    codigo_regional varchar(120) NOT NULL,
    id_origem varchar(240) NOT NULL,
    coletado_em timestamptz NOT NULL,
    conteudo_sha256 varchar(64) NOT NULL CHECK (conteudo_sha256 ~ '^[0-9a-f]{64}$'),
    sincronizado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (codigo_regional, id_origem),
    FOREIGN KEY (codigo_regional, id_origem)
        REFERENCES operacional.links_internet(codigo_regional, id_origem)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

GRANT UPDATE ON operacional.links_internet TO sentinel_collector;
GRANT SELECT, INSERT, UPDATE ON operacional.sincronizacoes_links TO sentinel_collector;
GRANT SELECT ON operacional.sincronizacoes_links TO sentinel_reader;

COMMIT;
