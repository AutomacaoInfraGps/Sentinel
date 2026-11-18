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
CREATE ROLE sentinel_admins_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
SET LOCAL ROLE sentinel_owner;
CREATE TABLE operacional.fontes_monitor_admins (
    id varchar(120) PRIMARY KEY CHECK (id = 'sentinel_admin_monitor'),
    cache_sha256 varchar(64) NOT NULL CHECK (cache_sha256 ~ '^[0-9a-f]{64}$'),
    baseline_sha256 varchar(64) NOT NULL CHECK (baseline_sha256 ~ '^[0-9a-f]{64}$'),
    firewalls_sha256 varchar(64) NOT NULL CHECK (firewalls_sha256 ~ '^[0-9a-f]{64}$'),
    catalogo_regionais_sha256 varchar(64) NOT NULL CHECK (catalogo_regionais_sha256 ~ '^[0-9a-f]{64}$'),
    fuso_origem varchar(120) NOT NULL,
    publicado_em timestamptz NOT NULL,
    digest_carga varchar(64) NOT NULL CHECK (digest_carga ~ '^[0-9a-f]{64}$'),
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE operacional.dispositivos_monitor_admins (
    fonte_id varchar(120) NOT NULL REFERENCES operacional.fontes_monitor_admins(id) ON DELETE RESTRICT,
    chave_dispositivo varchar(240) NOT NULL CHECK (btrim(chave_dispositivo) <> ''),
    nome varchar(240) NOT NULL CHECK (btrim(nome) <> ''),
    tipo varchar(30) NOT NULL CHECK (tipo IN ('fortigate','fortimanager','fortianalyzer','nao_identificado')),
    codigo_regional varchar(120) REFERENCES operacional.regionais(codigo) ON UPDATE CASCADE ON DELETE RESTRICT,
    vinculo_regional varchar(30) NOT NULL CHECK (vinculo_regional IN
        ('unico','central_sem_regional','somente_baseline','ambiguo','nao_encontrado')),
    presente_no_cache boolean NOT NULL,
    presente_na_baseline boolean NOT NULL,
    consulta_valida boolean,
    consulta_indisponivel boolean,
    monitoramento_limitado boolean,
    offline boolean,
    sem_permissao boolean,
    ultima_coleta_valida timestamptz,
    PRIMARY KEY(fonte_id,chave_dispositivo),
    CHECK (presente_no_cache OR presente_na_baseline),
    CHECK ((vinculo_regional = 'unico') = (codigo_regional IS NOT NULL)),
    CHECK (consulta_valida IS DISTINCT FROM TRUE OR
        (consulta_indisponivel IS DISTINCT FROM TRUE AND monitoramento_limitado IS DISTINCT FROM TRUE
         AND offline IS DISTINCT FROM TRUE AND sem_permissao IS DISTINCT FROM TRUE))
);
CREATE TABLE operacional.contas_admins_observadas (
    fonte_id varchar(120) NOT NULL,
    chave_dispositivo varchar(240) NOT NULL,
    usuario varchar(240) NOT NULL CHECK (btrim(usuario) <> ''),
    evidencia varchar(40) NOT NULL CHECK (evidencia IN ('consulta_valida_declarada','cache_sem_confirmacao_atual')),
    PRIMARY KEY(fonte_id,chave_dispositivo,usuario),
    FOREIGN KEY(fonte_id,chave_dispositivo) REFERENCES operacional.dispositivos_monitor_admins(fonte_id,chave_dispositivo)
        ON DELETE RESTRICT
);
CREATE TABLE operacional.baseline_admins_aprovada (
    fonte_id varchar(120) NOT NULL,
    chave_dispositivo varchar(240) NOT NULL,
    usuario varchar(240) NOT NULL CHECK (btrim(usuario) <> ''),
    PRIMARY KEY(fonte_id,chave_dispositivo,usuario),
    FOREIGN KEY(fonte_id,chave_dispositivo) REFERENCES operacional.dispositivos_monitor_admins(fonte_id,chave_dispositivo)
        ON DELETE RESTRICT
);
CREATE TABLE operacional.divergencias_monitor_admins (
    fonte_id varchar(120) NOT NULL,
    chave_dispositivo varchar(240) NOT NULL,
    usuario varchar(240) NOT NULL CHECK (btrim(usuario) <> ''),
    categoria varchar(30) NOT NULL CHECK (categoria IN ('novo','removido','remocao_pendente')),
    PRIMARY KEY(fonte_id,chave_dispositivo,usuario,categoria),
    FOREIGN KEY(fonte_id,chave_dispositivo) REFERENCES operacional.dispositivos_monitor_admins(fonte_id,chave_dispositivo)
        ON DELETE RESTRICT
);
REVOKE ALL ON operacional.fontes_monitor_admins, operacional.dispositivos_monitor_admins,
    operacional.contas_admins_observadas, operacional.baseline_admins_aprovada,
    operacional.divergencias_monitor_admins FROM PUBLIC, sentinel_reader, sentinel_api;
GRANT USAGE ON SCHEMA operacional TO sentinel_admins_reader;
GRANT SELECT ON operacional.fontes_monitor_admins, operacional.dispositivos_monitor_admins,
    operacional.contas_admins_observadas, operacional.baseline_admins_aprovada,
    operacional.divergencias_monitor_admins TO sentinel_admins_reader;
GRANT SELECT, INSERT ON operacional.fontes_monitor_admins, operacional.dispositivos_monitor_admins,
    operacional.contas_admins_observadas, operacional.baseline_admins_aprovada,
    operacional.divergencias_monitor_admins TO sentinel_collector;
COMMIT;
