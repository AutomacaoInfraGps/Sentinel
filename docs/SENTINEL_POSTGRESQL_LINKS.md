# Links de internet: auditoria antes da carga

VPNs tiveram carga e sincronizacao automatica homologadas pelo operador:
166 VPNs, 154 online/12 offline na coleta 2026-11-16 16:51:02 -03, digest e
marcador confirmados sem --apply. Links sao a proxima categoria, ainda sem SQL.

## Caminhos atuais verificados no codigo

- web_config._executar_sincronizacao_links_todas_regionais chama a coleta por
  regional. _load_regional_interfaces resolve equipamento/ADOM do FortiManager,
  busca configuracao de interfaces e combina monitoramento via proxy.
- Fontes retornadas incluem fortimanager, fortimanager_proxy_monitor e
  fortimanager_config+proxy_monitor. Nao presumir uma unica fonte pelo nome da
  tela. Ha tambem caminhos legados fortigate e fallback_local.
- _coletar_links_regional combina interface e membros SD-WAN/SLA. O status pode
  vir de SLA, interface ou equipamento desconectado; nao equivale apenas a ping.
- estrutura_regionais.json guarda links e links_internet_auto. A tela prefere
  a lista automatica quando ela existe, mesmo vazia; o caminho legado aplica
  selecao/filtros. Somar ambas as listas duplica links.
- _build_auto_link_id gera identificador regional/interface e acrescenta sufixo
  quando ha colisao. O ID nao e por si so uma identidade global do equipamento.
- Persistencias individuais/em lote podem substituir ultima_verificacao por
  horario local de gravacao, inclusive ao persistir fallback. Nao o tratar como
  uma coleta nova confirmada de status. Os formatos e cobertura precisam ser
  medidos antes da migracao.

Nada disso foi alterado nesta etapa. Nao modificar agora filtros, frequencias,
origem de status, cadastro, vinculacao, AD, SofIA ou gerenciador de atualizacoes.

## Auditoria segura no Rigel

Depois de commit/push e pull, sem reiniciar:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    C:\Automacao\scripts\database\audit_link_sources.py
```

Le somente estrutura_regionais.json, output/sentinel_operational_state.json e
output/mapa_monitoramento_cache.json com biblioteca padrao. Sem rede, SQL,
Flask ou DPAPI. Nao grava, nao consulta equipamentos e nao exporta registros,
IDs, nomes, IPs, comentarios, provedores, credenciais ou texto de erros.
Chaves JSON duplicadas sao recusadas. Origens/status/modos desconhecidos viram
categorias fixas, nunca nomes de campos/valores arbitrarios na saida.

O relatorio separa as duas listas do catalogo e as projecoes. Conta IDs repetidos
dentro/entre regionais, cobertura de regional+ID e regional+endpoint+interface,
presenca de serial/VDOM e tipos de horarios/IP. Nao usa nome como interface nem
infere serial a partir do endpoint. Sem catalogo valido, nenhum vinculo pode
ser confirmado. Valores zero numericos contam como presentes; booleanos nao
viram IDs. Duplicidades sao diagnostico, nao criterio automatico de fusao.

## Proximos passos

1. Rever auditoria real e decidir a fonte para cadastro e para observacoes.
2. Definir identidade/vinculo sem fundir links por provedor/IP, com tratamento
   explicito de listas automaticas vazias, fallback e dados de verificacao.
3. Preparar tabela/importador e testes; simular antes de qualquer escrita.
4. Backup, copias congeladas protegidas, migracao, carga e leitura com api.
5. So depois, persistencia paralela controlada e homologacao de coleta nova.

## Resultado real e carga inicial preparada

Auditoria do Rigel: 51 regionais; links tem 330 registros e cinco interfaces
repetidas na regional. links_internet_auto tem 88 registros, todos com ID,
interface/endpoint e vinculo regional, sem duplicidades; 84 online/4 offline.
85 com origem fortimanager_config+proxy_monitor e tres fortimanager.
Tres regionais nao possuem lista automatica. Estado e mapa mostram tambem 88.
Ha 50 IDs presentes em ambas as listas na mesma regional, sem comprovar que
todos os demais atributos coincidam. Nao fundir nem somar os dois conjuntos.

Preparados (ainda NAO aplicados ao Rigel):

- scripts/database/sql/008_link_catalog.sql, tabela operacional.links_internet.
- scripts/database/import_link_catalog.py, simulacao por padrao e escrita
  protegida somente no Rigel em tabela vazia.

A carga le APENAS links_internet_auto de estrutura_regionais.json. Nao refaz
filtros de apresentacao, nao importa do mapa, nao recorre a links nas tres
regionais sem lista e nao altera as listas originais. Lista automatica vazia
e respeitada; ausencia e vazia sao contadas separadamente. Os 330 registros do
cadastro legado continuam preservados no JSON e AINDA NAO foram migrados por
este importador. Migracao integral desse cadastro exige tratamento separado.

Chave: (codigo_regional, id_origem), ID exato do cadastro. Nao declarar esse ID
como identificador nativo permanente do firewall. Nao fundir por provedor/IP
nem gerar ID por posicao. Duplicidade de chave ou endpoint/interface dentro
da regional bloqueia a carga inteira. IDs repetidos entre regionais sao validos.

Serial, VDOM e coletado_em ausentes ficam NULL. Nao inferir serial de um IP nem
criar FK de firewall sem correlacao verificada. Interface_monitorada e endpoint
sao exigidos como atributos, nao usados para inventar o ID. regional tem FK
para regionais ja existentes. O papel SQL tecnico continua sem representar AD.

ultima_verificacao e armazenada como verificado_em, com fuso IANA EXPLICITO
--source-timezone para datas legadas sem fuso. verificacao_sem_fuso_na_origem
preserva essa condicao e fuso_verificacao_legada documenta a configuracao usada.
Esse horario pode ter sido atualizado em persistencia de fallback: NAO e uma
coleta nova confirmada, nem indica frescor garantido. coletado_em so recebe um
campo explicitamente existente e com fuso; nunca e copiado de verificado_em,
publicacao do cadastro, mtime ou relogio do importador.

Campos de perda de pacotes, modo SLA/interface e fontes sao preservados sem
recalcular o status. Booleanos/numeros/IPs sao validados; NaN/infinito/perda fora
de 0..100 sao recusados. SLA JSON bruto, comentarios, senhas e campos arbitrarios
nao entram no SQL nem nos relatorios. Desconhecidos textuais de modo/origem podem
ser preservados como atributos limitados, mas o resumo usa categoria fixa para
nao exportar valores arbitrarios. A auditoria passou a reconhecer explicitamente
monitor_zabbix_packet_loss e link_mode, ja existentes no codigo.

## Implantacao incremental

1. Commit/push e pull dos novos arquivos. Nao precisa reiniciar: nenhum hook
   de links foi acrescentado, nenhuma sincronizacao foi habilitada.
2. Rodar SOMENTE a simulacao:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    C:\Automacao\scripts\database\import_link_catalog.py `
    --source-timezone America/Sao_Paulo
```

3. Rever contagens, lacunas e digest. Nao executar SQL antes dessa revisao.
4. Novo pg_dump custom e pg_restore --list, seguido de copia congelada PROTEGIDA
   de estrutura_regionais.json no E:, fora do Git. Pode conter credenciais ou
   referencias do ambiente; nao compartilhar o arquivo inteiro.
5. Simular usando --source no arquivo congelado. Guardar seu digest_carga,
   que inclui hash bruto, fuso e registros tipados, nao apenas a lista resumida.
6. Aplicar SOMENTE 008 como sentinel_admin, psql -X/ON_ERROR_STOP=1.
7. Conferir copia com --check-database: tabela vazia e codigos existentes.
8. Aplicar copia com --apply --expected-digest do arquivo revisado.
9. Conferir como sentinel_api: contagem/status e totais das outras categorias.

Writer transacional, identidade sentinel_collector/sentinel/5433; lock de
regionais antes de links, timeouts, tabela vazia, parametros SQL, contagem
final total/por status. Migracao protege data_directory e owner. Reader somente
SELECT; coletor SELECT/INSERT, sem UPDATE/DELETE/TRUNCATE/CREATE. Testes locais
usam SQL simulado; migracao ainda exige homologacao PostgreSQL real.

Sem flag/sincronizacao automatica de links nesta etapa. Preservar as demais
sincronizacoes. Antes da escrita automatica, separar coleta real de fallback
e publicacao, para nao atualizar falsamente a atualidade dos dados no banco.
