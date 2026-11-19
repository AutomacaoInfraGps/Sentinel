# Preparacao da carga de firmware de switches

## Escopo aprovado

Manter Sentinel e Zabbix como estao. Os prints apresentados mostram os nomes
de login SWTGPS-BH7 em 10.31.0.26, SWTGLX03 em 10.254.12.29 e SWTGLX02 em
10.254.12.23. Nao mostram versoes nem comprovam a identidade fisica historica
dos registros de firmware. Nao usar esses prints para reassociar versoes antigas.

No Rigel foram auditados 140 registros: 137 candidatos concordantes,
1 ambiguo em BH, 1 conflito IP/nome em Galaxia e 1 sem correspondencia em
Uberlandia. Usuario decidiu manter os cadastros atuais e continuar preservando
as pendencias. Nenhuma correcao de nome, IP ou vinculo foi autorizada.

## Primeira etapa: simulacao e captura

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\capture_switch_firmware_catalog.py'
```

O comando padrao nao grava arquivo nem acessa PostgreSQL. Abre somente a
tabela de inventario SQLite, usando o leitor readonly da auditoria. Valida as
oito colunas conhecidas, hosts unicos, IPs, datas completas com fuso e origens
conhecidas. Dados invalidos, tabela ausente ou cache invalido bloqueiam a captura;
nao sao tratados como inventario vazio.

Depois de revisar o resumo, criar pasta nova e restrita em
E:\Sentinel\PostgreSQL\backups, seguindo as permissoes das cargas anteriores.
Nao usar pasta publica ou versionar o arquivo. O JSON contem nomes, IPs,
regionais textuais, modelos e versoes internos, mas nao credenciais ou jobs.
Exemplo para uma pasta ja criada e protegida:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\capture_switch_firmware_catalog.py' `
    --output 'E:\Sentinel\PostgreSQL\backups\PASTA_DA_CARGA\firmware-switches.json'
```

--output cria exclusivamente um arquivo novo, nunca sobrescreve. Se houver
falha de gravacao, nao reutilizar eventual arquivo parcial; a conferencia de
JSON e digest deve passar antes de qualquer carga. Nao copiar o SQLite inteiro:
ele tambem contem jobs e pode usar WAL ativo.

Para conferir o arquivo congelado sem reler SQLite/cache atuais:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\capture_switch_firmware_catalog.py' `
    --source 'E:\Sentinel\PostgreSQL\backups\PASTA_DA_CARGA\firmware-switches.json'
```

## Evidencia preservada

A captura guarda as oito colunas do inventario e um diagnostico de
correspondencia por registro. Nao inclui hostid, FK de switch, codigo regional
inferido, jobs, chaves ou credenciais. Mesmo concordancia IP/nome nao e vinculo
aprovado. As tres pendencias nao sao descartadas ou renomeadas.

sha256_inventario_projetado identifica a projecao canonica das oito colunas,
nao o arquivo SQLite fisico. sha256_cache_status identifica os bytes do cache
usado no diagnostico. digest_carga cobre toda a captura, inclusive horario e
diagnosticos; e verificacao de integridade, nao assinatura criptografica.
Fonte SQLite e cache JSON nao formam snapshot atomico conjunto; o cache e
relido para detectar alteracoes durante a captura. capturado_em e horario de
exportacao, nao uma nova consulta de firmware. checked_at_utc continua sendo
horario declarado do inventario; nao comprova atualizacao executada ou que
todos os atributos tenham sido detectados naquele instante.

## Captura confirmada no Rigel

Arquivo congelado:
E:\Sentinel\PostgreSQL\backups\carga-firmware-switches-20261119-073840-932\firmware-switches.json.
Capturado em 2026-11-19T10:38:43.358543+00:00, 140 registros com os mesmos
137 candidatos concordantes e 3 pendencias. Digest revisado:
53a51969fd08a9c57231c1b75e9a28bf16bbc8a7422bb58acd5c5310764a72fb.
Inventario projetado: 960439a310abf10236c7432d16ef921ef537bcc8a4162688cf0d7f0f4424f3bb.
Backup anterior a migracao informado como feito pelo usuario; caminho/tamanho
desse backup ainda nao recebidos. Migracao 023 e carga confirmadas no Rigel:
1 fonte, 140 registros e conteudo_confere_com_captura=true, com o mesmo digest.
Sincronizacao manual posterior descrita em SENTINEL_POSTGRESQL_SWITCHES_FIRMWARE_SYNC.md.

## Migracao 023 e carga inicial

A migracao cria fontes_firmware_switches e inventario_firmware_switches no
schema operacional. Nao adiciona FK para switches ou regionais nem altera
cadastros existentes. Mesmo os 137 candidatos sao armazenados somente como
diagnostico: vinculo_confirmado=false e imposto por CHECK. Os nomes originais,
IP textual, modelo, versao e horario textual/com fuso sao preservados.

Leitura restrita a sentinel_firmware_reader NOLOGIN, sem associacao automatica
ao usuario da API/DBeaver. Collector recebe SELECT e INSERT, sem UPDATE/DELETE.
Nao ampliar permissoes por causa de permission denied: conferir contagens com
sentinel_admin no psql. A migracao valida banco, porta e data_directory.

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' `
    -X -h 127.0.0.1 -p 5433 `
    -U sentinel_admin -d sentinel -W `
    -v ON_ERROR_STOP=1 `
    --file='C:\Automacao\scripts\database\sql\023_switch_firmware_catalog.sql'
```

Conferir somente leitura antes de aplicar:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\import_switch_firmware_catalog.py' `
    --source 'E:\Sentinel\PostgreSQL\backups\carga-firmware-switches-20261119-073840-932\firmware-switches.json' `
    --check-database
```

Esperado antes da carga: ambas as contagens zero, tabelas_firmware_vazias=true
e conteudo_confere_com_captura=false. Apenas apos revisar essa conferencia,
aplicar com o mesmo --source, --apply e --expected-digest com o digest acima.
O comando sem --check-database/--apply apenas simula, sem conexao SQL.

O importador valida novamente formato e hashes da captura, rele o arquivo,
exige RIGEL, banco sentinel/porta 5433/collector e digest exato na gravacao.
Usa advisory lock, tabelas inicialmente vazias, INSERT parametrizado e
conferencia tipada de todos os campos antes do commit. Nao executa upsert,
UPDATE, DELETE ou releitura das fontes vivas. Erros cancelam a transacao;
sucesso so e emitido depois de sair do contexto de commit. Repeticao da carga
inicial e bloqueada. Hashes preservam evidencia de integridade, nao aprovacao
da identidade dos equipamentos.

Depois da aplicacao, repetir --check-database: esperado 1 fonte, 140 registros
e conteudo_confere_com_captura=true. Conferencia administrativa complementar:

```sql
SELECT (SELECT count(*) FROM operacional.fontes_firmware_switches) AS fontes,
       count(*) AS registros,
       count(*) FILTER (WHERE vinculo_confirmado) AS vinculos_confirmados
FROM operacional.inventario_firmware_switches;

SELECT diagnostico_vinculo, count(*) AS registros
FROM operacional.inventario_firmware_switches
GROUP BY diagnostico_vinculo ORDER BY diagnostico_vinculo;
```

Esperado: 1 fonte, 140 registros, zero vinculos confirmados; diagnosticos
137 concordantes, 1 ambiguo, 1 conflito IP/nome e 1 sem correspondencia.
Nao reiniciar PostgreSQL ou o aplicativo para essa carga. A tela continua
usando as fontes anteriores. Sincronizacao automatica nao foi implementada;
jobs, credenciais e consultas a equipamentos permanecem fora do escopo.
