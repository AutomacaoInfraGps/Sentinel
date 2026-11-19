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
CREATE ROLE sentinel_firmware_reader NOLOGIN;
SET LOCAL ROLE sentinel_owner;
CREATE TABLE operacional.fontes_firmware_switches (
    id varchar(120) PRIMARY KEY CHECK (id = 'sentinel_switch_firmware_sqlite'),
    versao integer NOT NULL CHECK (versao = 1),
    capturado_em timestamptz NOT NULL,
    inventario_projetado_sha256 varchar(64) NOT NULL CHECK (inventario_projetado_sha256 ~ '^[0-9a-f]{64}$'),
    cache_status_sha256 varchar(64) NOT NULL CHECK (cache_status_sha256 ~ '^[0-9a-f]{64}$'),
    digest_carga varchar(64) NOT NULL CHECK (digest_carga ~ '^[0-9a-f]{64}$'),
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE operacional.inventario_firmware_switches (
    fonte_id varchar(120) NOT NULL REFERENCES operacional.fontes_firmware_switches(id) ON DELETE RESTRICT,
    ordem integer NOT NULL CHECK (ordem > 0),
    host_origem varchar(255) NOT NULL CHECK (btrim(host_origem) <> ''),
    nome_origem varchar(255) NOT NULL CHECK (btrim(nome_origem) <> ''),
    regional_origem varchar(255) NOT NULL CHECK (btrim(regional_origem) <> ''),
    ip_origem varchar(255) NOT NULL CHECK (btrim(ip_origem) <> ''),
    modelo_declarado varchar(255) NOT NULL CHECK (btrim(modelo_declarado) <> ''),
    versao_declarada varchar(255) NOT NULL CHECK (btrim(versao_declarada) <> ''),
    consulta_textual varchar(80) NOT NULL CHECK (btrim(consulta_textual) <> ''),
    consulta_declarada_em timestamptz NOT NULL,
    origem_consulta varchar(255) NOT NULL CHECK (origem_consulta IN ('webui','bulk_webui','snmp','ssh','manual')),
    diagnostico_vinculo varchar(80) NOT NULL CHECK (diagnostico_vinculo IN (
        'enderecos_da_fonte_conflitantes', 'ambiguo_nao_aprovado',
        'candidato_sem_identidade_valida', 'ip_e_nome_apontam_identidades_diferentes',
        'ip_e_nome_concordantes_candidato', 'apenas_ip_candidato_nao_aprovado',
        'apenas_nome_candidato_nao_aprovado', 'sem_correspondencia')),
    vinculo_confirmado boolean NOT NULL DEFAULT false CHECK (NOT vinculo_confirmado),
    importado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (fonte_id, host_origem),
    UNIQUE (fonte_id, ordem)
);
REVOKE ALL ON operacional.fontes_firmware_switches, operacional.inventario_firmware_switches
    FROM PUBLIC, sentinel_reader, sentinel_api;
GRANT USAGE ON SCHEMA operacional TO sentinel_firmware_reader;
GRANT SELECT ON operacional.fontes_firmware_switches, operacional.inventario_firmware_switches TO sentinel_firmware_reader;
GRANT SELECT, INSERT ON operacional.fontes_firmware_switches, operacional.inventario_firmware_switches TO sentinel_collector;
COMMIT;
