# Auditoria das lacunas de Switches

## Execucao

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\audit_switch_sources.py'
```

Enviar somente o resumo JSON. Sem PostgreSQL, SQLite, Zabbix, SNMP, SSH,
cofre ou agendador. Nao altera fontes nem executa verificacao/atualizacao de
firmware. Nao exporta nomes, IDs, regionais, IPs, modelos, versoes, locais,
motivos brutos, alertas ou credenciais. Contabiliza presenca dos campos,
identidades, duplicidades e formatos de data, com hashes dos bytes JSON.

## Fontes usadas pela tela

/switches prefere output/switches_status_cache.json. Se nao houver registros,
usa instancia do gerenciador, depois cache operacional fresco, e pode chamar
carregamento API/planilha como fallback. A auditoria nao executa esses caminhos
nem afirma qual deles foi escolhido em uma requisicao real de usuario.

Audita separadamente o cache de status e o grupo switches de
output/sentinel_operational_state.json. Identidade segue a projecao SQL:
zabbix+hostid valido ou local+nome normalizado apenas com local_only=true.
Nome/IP nao sao usados para fundir identidades Zabbix. Uma identidade ausente
de uma fonte nao prova remocao do equipamento; as fontes podem ter ciclos
diferentes. Cada arquivo e relido para verificar estabilidade, mas as fontes
nao formam uma transacao conjunta e o frescor nao e aplicado pelo auditor.

output/switches_metadata.json fornece ajustes de modelo/local/CORE. A pagina
aplica esses ajustes e resolve CORE por regional. A auditoria mede candidatos
por hostid e fallback por nome, conflitos entre as duas chaves e metadados sem
uso pela chave prioritaria; nao aplica os ajustes nem aprova novos vinculos.
Registro de metadado sem uso nao e lixo para apagar automaticamente.

Firmware vem de data/switch_updates/scheduled_updates.sqlite3, tabela
switch_firmware_inventory, consultada pelo scheduler. A tela cruza host/IP
ou switch_name e pode ajustar o modelo pelo resultado. Esta auditoria apenas
verifica a existencia desse arquivo padrao: nao abre SQLite, inicializa seu
schema, le jobs ou consulta inventario. O estado presente_conteudo_nao_auditado
significa pendencia, nao firmware ausente. Proxima auditoria deve usar snapshot
SQLite consistente/controle somente leitura sem acionar o scheduler; nao
copiar apenas o arquivo principal ignorando WAL de um banco em uso.

## Campos SQL e lacunas

004/005 persistem inventario, identidade da origem, vinculo regional,
endereco/IP, modelo/origem, local, CORE/origem, status/verificacao, manutencao
e quantidade de alertas. warning_problemas entra como quantidade, nao texto.
False, zero e listas vazias sao distintos de ausencia; cobertura de
em_manutencao nao significa quantidade de equipamentos em manutencao.
Booleanos invalidos, listas/itens de alertas invalidos sao diagnosticados.
Um endereco que nao e IP pode ser DNS permitido no cadastro; o auditor nao
faz resolucao nem o declara um endereco invalido por isso.

Ficam fora da projecao status_reason, status_details, warning_resumo, textos
individuais dos alertas e inventario de firmware/data da consulta. Textos
brutos podem conter detalhes internos e exigem definicao de acesso antes de
persistencia; nao ampliar permissoes de leitores gerais implicitamente.

Portas/interfaces sao contadas somente quando presentes nesses JSONs.
Interfaces do host Zabbix (endereco de gerenciamento) nao sao automaticamente
inventario das portas fisicas do switch. Alguns itens de interfaces sao
usados na verificacao de status; ausencia nos caches nao prova que nunca
foram consultados. Nao criar historico ou tabela de portas a partir de nomes.

A cobertura SQL declarada vem do codigo, nao de consulta ao PostgreSQL real.
A auditoria nao confere marcadores, contagens SQL, permissoes ou vinculos
regionais. Nao usa ultima_verificacao/updated_at como prova de consulta de
firmware; esse inventario tem evidencia temporal propria no SQLite.

## Proxima etapa

Revisar o resultado real do Rigel e conferir contagens/marcador em PostgreSQL.
Investigar diferencas de inventario e IPs repetidos sem apagar/fundir por
palpite. Auditar o firmware separado em etapa propria antes de modelar sua
identidade ou copiar jobs. So depois preparar extensao tipada, backup e
conferencia. Nenhuma migracao, leitor ou escritor de Switches foi alterado.
