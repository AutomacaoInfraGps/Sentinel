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
CREATE TABLE operacional.fontes_cadastro_vms (
    id varchar(120) PRIMARY KEY CHECK (id = 'sentinel_vm_cadastro'),
    arquivo_origem_sha256 varchar(64) NOT NULL CHECK (arquivo_origem_sha256 ~ '^[0-9a-f]{64}$'),
    catalogo_regionais_sha256 varchar(64) NOT NULL CHECK (catalogo_regionais_sha256 ~ '^[0-9a-f]{64}$'),
    fuso_verificacao_legada varchar(120),
    digest_carga varchar(64) NOT NULL CHECK (digest_carga ~ '^[0-9a-f]{64}$'),
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE operacional.maquinas_virtuais (
    fonte_id varchar(120) NOT NULL REFERENCES operacional.fontes_cadastro_vms(id) ON DELETE RESTRICT,
    id_origem varchar(240) NOT NULL CHECK (id_origem = btrim(id_origem) AND id_origem <> ''),
    nome varchar(240) NOT NULL CHECK (btrim(nome) <> ''),
    ip inet NOT NULL,
    codigo_regional varchar(120) NOT NULL REFERENCES operacional.regionais(codigo) ON UPDATE CASCADE ON DELETE RESTRICT,
    regional_origem varchar(240) NOT NULL CHECK (btrim(regional_origem) <> ''),
    regra_vinculo varchar(40) NOT NULL CHECK (regra_vinculo IN ('codigo_exato_aprovado','rotulo_rj_confirmado')),
    descricao varchar(2000),
    status_declarado varchar(40) NOT NULL CHECK (lower(status_declarado) IN
        ('running','stopped','unknown','unreachable','online','offline','paused','saved','starting','stopping','error')),
    ultima_verificacao timestamptz,
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(fonte_id,id_origem),
    UNIQUE(fonte_id,ip)
);
REVOKE ALL ON operacional.fontes_cadastro_vms, operacional.maquinas_virtuais FROM PUBLIC;
GRANT SELECT ON operacional.fontes_cadastro_vms, operacional.maquinas_virtuais TO sentinel_reader;
GRANT SELECT, INSERT ON operacional.fontes_cadastro_vms, operacional.maquinas_virtuais TO sentinel_collector;
COMMIT;
