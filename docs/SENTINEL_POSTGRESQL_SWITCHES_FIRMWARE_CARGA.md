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

## Proxima etapa

Revisar a simulacao no Rigel, congelar a projecao, fazer backup PostgreSQL e
entao preparar a migracao e importador transacional com digest esperado.
Esta entrega ainda nao cria tabelas nem grava no PostgreSQL, nao muda a tela,
nao habilita sincronizacao automatica e nao altera jobs ou dispositivos.
