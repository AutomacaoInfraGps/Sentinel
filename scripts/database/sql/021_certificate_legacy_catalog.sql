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
CREATE ROLE sentinel_certificados_reader NOLOGIN;
SET LOCAL ROLE sentinel_owner;
CREATE TABLE operacional.fontes_certificados_legados (
    id varchar(120) PRIMARY KEY CHECK (id = 'sentinel_certificados_relatorio_legado'),
    arquivo_origem_sha256 varchar(64) NOT NULL CHECK (arquivo_origem_sha256 ~ '^[0-9a-f]{64}$'),
    digest_carga varchar(64) NOT NULL CHECK (digest_carga ~ '^[0-9a-f]{64}$'),
    origem_confirmada boolean NOT NULL DEFAULT false CHECK (NOT origem_confirmada),
    host_origem varchar(255) CHECK (host_origem IS NULL),
    repositorio_origem varchar(255) CHECK (repositorio_origem IS NULL),
    codigo_regional varchar(120) CHECK (codigo_regional IS NULL),
    coletado_em timestamptz CHECK (coletado_em IS NULL),
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE operacional.certificados_legados (
    fonte_id varchar(120) NOT NULL REFERENCES operacional.fontes_certificados_legados(id) ON DELETE RESTRICT,
    ordem integer NOT NULL CHECK (ordem > 0),
    thumbprint_textual varchar(200) NOT NULL CHECK (btrim(thumbprint_textual) <> ''),
    thumbprint_normalizado varchar(64) NOT NULL CHECK (thumbprint_normalizado ~ '^([0-9A-F]{40}|[0-9A-F]{64})$'),
    assunto varchar(4000) NOT NULL CHECK (btrim(assunto) <> ''),
    emissor varchar(4000) NOT NULL CHECK (btrim(emissor) <> ''),
    vencimento_textual varchar(80) NOT NULL CHECK (btrim(vencimento_textual) <> ''),
    vencimento_declarado timestamptz NOT NULL,
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (fonte_id,thumbprint_normalizado),
    UNIQUE (fonte_id,ordem)
);
REVOKE ALL ON operacional.fontes_certificados_legados, operacional.certificados_legados
    FROM PUBLIC, sentinel_reader, sentinel_api;
GRANT USAGE ON SCHEMA operacional TO sentinel_certificados_reader;
GRANT SELECT ON operacional.fontes_certificados_legados, operacional.certificados_legados TO sentinel_certificados_reader;
GRANT SELECT, INSERT ON operacional.fontes_certificados_legados, operacional.certificados_legados TO sentinel_collector;
COMMIT;
