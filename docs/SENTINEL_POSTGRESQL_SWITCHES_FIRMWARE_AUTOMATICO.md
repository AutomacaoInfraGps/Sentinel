# Espelhamento automatico de firmware

## Estado de partida

Rigel: migracoes 023/024 aplicadas, 140 registros preservados e presentes,
137 candidatos e 3 pendencias sem vinculos. Sincronizacao manual de nova
captura confirmada: 2026-11-19T08:20:38.228239-03:00, digest
459b7b5a9f62c0ecc6606e9f4694d18f3f70ed3da56a94e967e4a4197f2d8caf.
Automatizacao ativada e recorrencia confirmada no Rigel em 19/11/2026:
primeiro commit 11:35:41.763596 UTC (08:35:41 -03:00), segundo commit
11:40:43.554960 UTC (08:40:43 -03:00), capturas 11:35:38.142989 e
11:40:41.806194 UTC. Ambos com 140 registros; inventario projetado manteve hash
960439a310abf10236c7432d16ef921ef537bcc8a4162688cf0d7f0f4424f3bb.
Isso comprova dois ciclos, nao nova coleta de firmware ou saude futura continua.

## Escopo

services/operational_switch_firmware.py inicia pelo run_web_service.py, sem
depender de visita a pagina. Thread daemon unica por processo, intervalo de
300 segundos e file lock entre processos. Usa o writer validado da etapa 024
e o mesmo advisory lock SQL de carga/sync manual. Nao exige nova migracao SQL.

Somente no RIGEL e com flag enabled exatamente true. Ausente, false, invalido
ou fora do Rigel: nao le SQLite/cache e nao conecta SQL. Nao cria flag habilitada
automaticamente. Paths sao fixos, relativos a PROJECT_ROOT:

- instance/operational-postgres-firmware-shadow.json
- data/switch_updates/scheduled_updates.sqlite3
- output/switches_status_cache.json

Captura apenas as oito colunas da tabela de firmware por transacao readonly
SQLite, respeitando WAL. Usa a mesma validacao/canonizacao e diagnostico do
arquivo congelado. O cache e relido para detectar mudancas durante a captura.
SQLite e JSON nao formam transacao atomica conjunta. O SQLite pode usar
bookkeeping WAL/SHM, sem gravar dados logicos. Nao importa o scheduler, le jobs,
agenda atualizacoes, consulta equipamentos ou busca credenciais de switches.
A conexao SQL usa somente o collector ja configurado.

Falha de leitura, schema ausente, inventario vazio/invalido ou consulta declarada
futura bloqueiam o ciclo. Mantem controles contra captura antiga e consulta
regressiva/conflitante por host, ausencia sem DELETE e vinculo_confirmado=false.
Reconfere flag antes de gravar e antes de sair da transacao. Falha do banco ou
desabilitacao durante escrita causa rollback. Avisos omitem excecoes brutas.

Quando todos os campos tipados presentes ja conferem, atualiza somente o
marcador SQL; nao regrava inventario nem atualizado_em das linhas. Caso haja
mudanca, usa o upsert e a conferencia final ja validados. capturado_em e
sincronizado_em NAO comprovam consulta recente de firmware. Os tres pendentes
nao sao corrigidos ou vinculados automaticamente.

## Publicacao e conferencia antes de ativar

Publicar codigo, fazer pull no Rigel, mantendo o flag desabilitado/ausente.

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\sync_switch_firmware_catalog.py' `
    --current
```

--current apenas captura as fontes locais e compara com SQL readonly. Nao roda
o poller nem aceita --apply. Fontes atuais sao apenas para conferencia;
gravacao manual continua exigindo --source congelado e digest revisado.

Interpretacao dos campos:

- conteudo_atual_confere: todos os campos presentes SQL iguais a projecao atual.
- conteudo_ja_sincronizado: exige tambem marcador EXATAMENTE igual ao recibo,
  incluindo horario e hash do cache. Em --current tende a ser false porque a
  captura acabou de ser criada; nao e erro se conteudo_atual_confere=true.
- ultima_captura_sincronizada: horario da exportacao aceita pelo banco.
- sincronizacao_automatica_firmware em --current: estado do flag, nao prova
  de que o processo do servico foi reiniciado ou concluiu um ciclo.

O cache pode mudar sem mudar diagnosticos/firmware; comparar hashes e datas
nao substitui a conferencia tipada de conteudo.

## Ativacao controlada

Apos conferir o estado atual, no Rigel e sob a mesma conta operacional:

```powershell
if ($env:COMPUTERNAME -ne 'RIGEL') { throw 'Execute somente no Rigel.' }
Set-Content -LiteralPath 'C:\Automacao\instance\operational-postgres-firmware-shadow.json' `
    -Value '{"enabled":true}' -Encoding utf8

powershell -ExecutionPolicy Bypass -File C:\Automacao\restart_web_service.ps1
```

Reiniciar somente o servico web pelo script existente, mantendo conta e
credenciais; nao reiniciar PostgreSQL, alterar o servico ou ativar jobs.
O worker tenta um ciclo inicial e depois a cada 5 minutos. Confirmar:

```powershell
Get-Content -LiteralPath 'C:\Automacao\output\firmware_postgres_sync_status.json' -Raw

& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\sync_switch_firmware_catalog.py' `
    --current
```

O status e escrito atomicamente SOMENTE depois do commit. Contem apenas
hashes, contagens, diagnosticos agregados e horarios, nunca inventario bruto,
nomes, IPs, modelos, versoes ou credenciais. Nao e um recibo reaplicavel:
para carga manual, usar captura congelada completa e restrita.

Conferir status recente e marcador SQL avancando alem de 08:20:38, 140 presentes
ou mudancas legitimas revisadas, conteudo_atual_confere=true, sem vinculos.
Confirmar outro ciclo depois de 5 minutos para comprovar recorrencia.
Status antigo pode ser da ultima execucao bem-sucedida: nao prova saude atual.
Se falhar a escrita do status APOS commit, SQL pode estar atualizado; conferir
o banco antes de repetir qualquer gravacao. Um problema nao derruba o web.

## Desativar

```powershell
Set-Content -LiteralPath 'C:\Automacao\instance\operational-postgres-firmware-shadow.json' `
    -Value '{"enabled":false}' -Encoding utf8
```

Flag e relido em cada ciclo e antes de confirmar escrita. Nao precisa excluir
dados ou reiniciar PostgreSQL. Um commit ja concluido nao e desfeito por essa
mudanca. Nenhuma leitura da tela foi migrada ao PostgreSQL nesta entrega.
