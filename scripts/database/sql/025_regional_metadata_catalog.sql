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
CREATE ROLE sentinel_regionais_metadados_reader NOLOGIN;
SET LOCAL ROLE sentinel_owner;
CREATE TABLE operacional.fontes_metadados_regionais (
    id varchar(120) PRIMARY KEY CHECK (id = 'sentinel_metadados_regionais'),
    versao integer NOT NULL CHECK (versao = 1),
    capturado_em timestamptz NOT NULL,
    publicacao_textual varchar(80) NOT NULL,
    arquivo_origem_sha256 varchar(64) NOT NULL CHECK (arquivo_origem_sha256 ~ '^[0-9a-f]{64}$'),
    metadados_sha256 varchar(64) NOT NULL CHECK (metadados_sha256 ~ '^[0-9a-f]{64}$'),
    digest_carga varchar(64) NOT NULL CHECK (digest_carga ~ '^[0-9a-f]{64}$'),
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE operacional.metadados_regionais (
    codigo_regional varchar(120) PRIMARY KEY
        REFERENCES operacional.regionais(codigo) ON UPDATE CASCADE ON DELETE RESTRICT,
    fonte_id varchar(120) NOT NULL REFERENCES operacional.fontes_metadados_regionais(id) ON DELETE RESTRICT,
    nome_origem varchar(240) NOT NULL CHECK (btrim(nome_origem) <> ''),
    descricao varchar(500) NOT NULL CHECK (btrim(descricao) <> ''),
    estado varchar(2) NOT NULL CHECK (estado IN (
        'AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA',
        'PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO')),
    uf varchar(2) NOT NULL CHECK (uf = estado),
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
REVOKE ALL ON operacional.fontes_metadados_regionais, operacional.metadados_regionais
    FROM PUBLIC, sentinel_reader, sentinel_api;
GRANT USAGE ON SCHEMA operacional TO sentinel_regionais_metadados_reader;
GRANT SELECT ON operacional.fontes_metadados_regionais, operacional.metadados_regionais TO sentinel_regionais_metadados_reader;
GRANT SELECT, INSERT ON operacional.fontes_metadados_regionais, operacional.metadados_regionais TO sentinel_collector;
COMMIT;
