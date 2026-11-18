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
CREATE ROLE sentinel_replicacao_reader NOLOGIN;
SET LOCAL ROLE sentinel_owner;
CREATE TABLE operacional.fontes_replicacao_ad (
    id varchar(120) PRIMARY KEY CHECK (id = 'sentinel_replicacao_ad_local'),
    arquivo_origem_sha256 varchar(64) NOT NULL CHECK (arquivo_origem_sha256 ~ '^[0-9a-f]{64}$'),
    digest_carga varchar(64) NOT NULL CHECK (digest_carga ~ '^[0-9a-f]{64}$'),
    fuso_legado varchar(120),
    publicacao_textual varchar(80) NOT NULL CHECK (btrim(publicacao_textual) <> ''),
    publicado_em_declarado timestamptz NOT NULL,
    totais_declarados jsonb NOT NULL CHECK (jsonb_typeof(totais_declarados) = 'object'),
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE operacional.observacoes_replicacao_ad (
    fonte_id varchar(120) NOT NULL REFERENCES operacional.fontes_replicacao_ad(id) ON DELETE RESTRICT,
    ordem integer NOT NULL CHECK (ordem > 0),
    nome varchar(255) NOT NULL CHECK (btrim(nome) <> ''),
    nome_identidade varchar(255) NOT NULL CHECK (btrim(nome_identidade) <> ''),
    secao varchar(20) NOT NULL CHECK (secao IN ('Origem','Destino')),
    status_declarado varchar(40) NOT NULL CHECK (lower(status_declarado) IN ('ok','warning','error','unknown')),
    delta_declarado varchar(240),
    parceiros_declarados integer CHECK (parceiros_declarados >= 0),
    falhas_declaradas integer CHECK (falhas_declaradas >= 0),
    erros_declarados integer CHECK (erros_declarados >= 0),
    replicacoes_declaradas integer CHECK (replicacoes_declaradas >= 0),
    ultima_replicacao_textual varchar(80),
    ultima_replicacao_declarada timestamptz,
    detalhes_declarados varchar(8000),
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (fonte_id,ordem),
    UNIQUE (fonte_id,nome_identidade,secao)
);
CREATE TABLE operacional.erros_operacionais_replicacao_ad (
    fonte_id varchar(120) NOT NULL REFERENCES operacional.fontes_replicacao_ad(id) ON DELETE RESTRICT,
    ordem integer NOT NULL CHECK (ordem > 0),
    mensagem_declarada varchar(8000) NOT NULL CHECK (btrim(mensagem_declarada) <> ''),
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (fonte_id,ordem)
);
REVOKE ALL ON operacional.fontes_replicacao_ad, operacional.observacoes_replicacao_ad,
    operacional.erros_operacionais_replicacao_ad FROM PUBLIC;
GRANT USAGE ON SCHEMA operacional TO sentinel_replicacao_reader;
GRANT SELECT ON operacional.fontes_replicacao_ad, operacional.observacoes_replicacao_ad,
    operacional.erros_operacionais_replicacao_ad TO sentinel_replicacao_reader;
GRANT SELECT, INSERT ON operacional.fontes_replicacao_ad, operacional.observacoes_replicacao_ad,
    operacional.erros_operacionais_replicacao_ad TO sentinel_collector;
COMMIT;
