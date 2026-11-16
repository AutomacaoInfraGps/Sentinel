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

CREATE TABLE operacional.servidores (
    codigo_regional varchar(120) NOT NULL
        REFERENCES operacional.regionais(codigo) ON UPDATE CASCADE ON DELETE RESTRICT,
    id_origem varchar(240) NOT NULL CHECK (id_origem = btrim(id_origem) AND id_origem <> ''),
    nome varchar(240) NOT NULL CHECK (nome = btrim(nome) AND nome <> ''),
    tipo varchar(120),
    ip inet,
    modelo varchar(240),
    funcao varchar(240),
    sistema_operacional varchar(240),
    status varchar(120),
    ativo boolean,
    ultima_verificacao timestamptz,
    tempo_resposta double precision CHECK (
        tempo_resposta >= 0 AND tempo_resposta < 'Infinity'::double precision),
    fonte varchar(40) NOT NULL DEFAULT 'estrutura_regionais'
        CHECK (fonte = 'estrutura_regionais'),
    arquivo_origem_sha256 varchar(64) NOT NULL
        CHECK (arquivo_origem_sha256 ~ '^[0-9a-f]{64}$'),
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (codigo_regional, id_origem)
);

GRANT SELECT ON operacional.servidores TO sentinel_reader;
GRANT SELECT, INSERT ON operacional.servidores TO sentinel_collector;

COMMIT;
