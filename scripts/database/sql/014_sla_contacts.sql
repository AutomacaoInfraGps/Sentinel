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
CREATE ROLE sentinel_contatos_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
SET LOCAL ROLE sentinel_owner;

CREATE TABLE operacional.fontes_contatos_sla (
    id varchar(120) PRIMARY KEY CHECK (id = 'sentinel_sla_principal'),
    aba varchar(128) NOT NULL CHECK (btrim(aba) <> ''),
    arquivo_origem_sha256 varchar(64) NOT NULL CHECK (arquivo_origem_sha256 ~ '^[0-9a-f]{64}$'),
    catalogo_regionais_sha256 varchar(64) NOT NULL CHECK (catalogo_regionais_sha256 ~ '^[0-9a-f]{64}$'),
    digest_carga varchar(64) NOT NULL CHECK (digest_carga ~ '^[0-9a-f]{64}$'),
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE operacional.regionais_contatos_sla (
    fonte_id varchar(120) NOT NULL REFERENCES operacional.fontes_contatos_sla(id) ON DELETE RESTRICT,
    codigo_regional varchar(120) NOT NULL REFERENCES operacional.regionais(codigo) ON UPDATE CASCADE ON DELETE RESTRICT,
    rotulo_regional_origem varchar(240) NOT NULL CHECK (btrim(rotulo_regional_origem) <> ''),
    rotulo_fortianalyzer_origem varchar(500) NOT NULL CHECK (btrim(rotulo_fortianalyzer_origem) <> ''),
    regra_vinculo varchar(40) NOT NULL CHECK (regra_vinculo IN ('identidade_normalizada_unica','alias_sla_verificado')),
    linha_planilha_origem integer NOT NULL CHECK (linha_planilha_origem >= 2),
    PRIMARY KEY(fonte_id,codigo_regional),
    UNIQUE(fonte_id,rotulo_regional_origem),
    UNIQUE(fonte_id,rotulo_fortianalyzer_origem)
);
CREATE TABLE operacional.contatos_regionais_sla (
    fonte_id varchar(120) NOT NULL,
    codigo_regional varchar(120) NOT NULL,
    papel varchar(20) NOT NULL CHECK (papel IN ('diretor','gerente','apoio_1','apoio_2')),
    nome_origem varchar(500) CHECK (nome_origem IS NULL OR btrim(nome_origem) <> ''),
    email_origem varchar(2000) CHECK (email_origem IS NULL OR btrim(email_origem) <> ''),
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(fonte_id,codigo_regional,papel),
    FOREIGN KEY(fonte_id,codigo_regional) REFERENCES operacional.regionais_contatos_sla(fonte_id,codigo_regional)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CHECK (nome_origem IS NOT NULL OR email_origem IS NOT NULL)
);
REVOKE ALL ON operacional.fontes_contatos_sla, operacional.regionais_contatos_sla,
    operacional.contatos_regionais_sla FROM PUBLIC, sentinel_reader, sentinel_api;
GRANT USAGE ON SCHEMA operacional TO sentinel_contatos_reader;
GRANT SELECT ON operacional.fontes_contatos_sla, operacional.regionais_contatos_sla,
    operacional.contatos_regionais_sla TO sentinel_contatos_reader;
GRANT SELECT, INSERT ON operacional.fontes_contatos_sla, operacional.regionais_contatos_sla,
    operacional.contatos_regionais_sla TO sentinel_collector;
COMMIT;
