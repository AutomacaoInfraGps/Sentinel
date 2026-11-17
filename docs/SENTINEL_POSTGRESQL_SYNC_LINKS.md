# Persistencia paralela de links

## Base homologada

Operador confirmou migracao 008 e carga inicial: 88 links em 48 regionais,
84 online e quatro offline, com leitura por sentinel_api. Todos sem coleta
explicita na carga, preservando o horario legado. Nao repetir 008 ou bootstrap.

Os 330 registros da lista links nao foram importados nem apagados; a fonte
operacional desta etapa continua sendo links_internet_auto.

## Evidencia de coleta sem mudar status

web_config._load_regional_interfaces acrescenta runtime_coletado_em em UTC
somente quando a chamada existente proxy_monitor_interfaces retorna dados.
_coletar_links_regional acrescenta data UTC de recebimento da resposta SD-WAN
quando a chamada existente e bem-sucedida. Nao cria chamada/API ou agendamento.

Cada link novo tem coleta_status_confirmada=False inicialmente, mesmo se o
registro anterior possuia True. So recebe True e coletado_em real quando:

- Membro SD-WAN da resposta atual produz status online/offline resolvido por
  perda de pacotes MONITOR_ZABBIX ou SLA ativo/inativo: sdwan_monitor.
- Ou a interface possui link_mode_status online/offline retornado pelo proxy
  atual e runtime_coletado_em: proxy_interface.

Presenca de membro com SLA desconhecido NAO confirma coleta. Status de mera
configuracao, dispositivo offline em inventario sem horario operacional ou
falha de consulta nao recebe frescor ficticio. Nenhuma regra atual de exibicao
de status foi alterada. Perda de pacotes antiga nao e exportada no SQL como
metrica nova quando a evidencia e somente interface.

Fallback persistido nas saidas de falha/ausencia de WAN tem marcador False,
mesmo se carregou um True antigo. A resposta individual em modo warning tambem
nao herda True. Datas antigas podem continuar no JSON como historico; o worker
exige True explicito para publicar. Coletado_em e excluido da assinatura que
conta alteracoes de cadastro, sem impedir salvamento das novas verificacoes.

## Publicacao e checkpoint

GerenciadorRegionais.salvar_regionais conserva o JSON e o hook de servidores.
Depois do replace original bem-sucedido chama o hook de links. O hook aceita
somente estrutura_regionais.json global, nao uma fonte filtrada por usuario.
Nao altera telas, rotas AD, SofIA ou gerenciador_atualizacoes.py.

services/operational_link_postgres.py projeta apenas campos permitidos de
links_internet_auto com evidencia completa. Dados antigos/configuracao/fallback
nao confirmados ficam fora da publicacao SQL, sem apagar seus registros no banco.
Um item marcado True mas malformado bloqueia a publicacao, em vez de ser
descartado silenciosamente. Codigos regionais precisam existir no SQL.

SQL usa regional+ID, nao fusao por provedor/IP ou serial presumido. Serial/VDOM
ausentes permanecem NULL. O verificado_em do registro SQL atualizado passa a
ser o instante da observacao confirmada; nao o timestamp_sync regravado na tela.
O timestamp da tela e o JSON original continuam com o comportamento anterior.

output/links_postgres_publication.json e um checkpoint separado, atomicamente
gravado com flush/fsync/replace e lock exclusivo entre processos (0,25s maximo).
Contem apenas campos operacionais e codigos regionais; sem outras categorias,
SLA JSON, comentarios, credenciais, refs DPAPI ou configuracao inteira.
Ainda contem IDs, IPs/endpoint e nomes: proteger com ACL operacional, nao
compartilhar o bruto nem commitar. O output permanece ignorado no Git.

O checkpoint retém a ultima observacao confirmada POR LINK ao combinar
publicacoes parciais. Nao remove link ausente nem o declara offline. Dados mais
antigos nao substituem novos; mesmo instante com conteudo diferente e conflito.
Mesmo se a ultima consulta falhar, o checkpoint pode conter observacoes antigas:
ele NAO e uma afirmacao de sucesso da consulta mais recente ou de frescor global.
Checkpoint corrompido exige diagnostico, nao reinicializacao silenciosa.

capturado_em e o horario real do hook depois de um salvamento, nao data da
coleta. Mudar capturado_em por outro salvamento do cadastro nao atualiza o
coletado_em de nenhum link. Resumos mostram a menor e a maior data de coleta;
nao interpretar a maior como prova de que todos os links foram consultados nela.

## SQL por link, fila e permissoes

009_link_shadow_sync.sql adiciona atualizado_no_banco_em, coleta_status_origem
e permite NULL no hash bruto. O marcador operacional.sincronizacoes_links tem
chave (codigo_regional,id_origem), com coleta e digest individuais. Nao usa um
marcador global para atribuir a todas as regionais a coleta de uma so.

Coletor recebe UPDATE de links e SELECT/INSERT/UPDATE do marcador. Reader apenas
SELECT do marcador. Sem DELETE/TRUNCATE/CREATE/MAINTAIN ou ampliacao de AD.
Guardas sentinel/5433/E:/Sentinel/PostgreSQL/data, owner sentinel_owner.

Writer em uma transacao, READ COMMITTED, lock_timeout 1s e statement_timeout 10s.
Locks regionais -> links -> marcadores. Parametros SQL para valores; identificadores
dinamicos sao somente constantes locais. Valida catalogo regional, processa cada
link por seu relogio e grava seu marcador depois do upsert/contagem. Qualquer
falha desfaz a transacao inteira. Observacao antiga nao sobrescreve nova.

Marcador igual e ignorado; marcador mais novo nao retrocede. Mesmo instante
com digest divergente e recusado. Marcador confirma observacao processada, nao
igualdade byte a byte se existir no SQL uma observacao ainda mais nova.
Hash bruto fica NULL no registro atualizado; procedencia vem do marcador
tipado. importado_em continua sendo a primeira insercao SQL.

Worker usa DPAPI/conta SQL coletora existente, sem rede SQL no thread que salva
JSON. Uma publicacao pendente mais uma em execucao. Ao substituir a pendente,
combina a observacao mais recente por chave, nao apenas a maior data global.
Nao e historico nem fila duravel. Falha aguarda nova publicacao normal; avisos
fixos e SQLSTATE, sem erro bruto. Desativar nao cancela transacao ja em andamento.

## Homologacao incremental no Rigel

1. Commit/push e pull mantendo ausente/desligado
   instance/operational-postgres-links-shadow.json. Exemplo versionado false.
2. Novo backup pg_dump custom e pg_restore --list antes de SOMENTE 009.
   Conferir catalogo nao substitui teste real de restauracao.
3. Aplicar 009 como sentinel_admin (psql -X/ON_ERROR_STOP=1).
4. Reiniciar pelo restart_web_service.ps1 e conferir healthz HTTP 200. Demais
   publicadores devem carregar o codigo novo pelo procedimento habitual,
   sem iniciar outro gerenciador/agendamento.
5. Executar sincronizacao/verificacao normal de links, aguardando conclusao.
   Se nao houver evidencia atual, nao fabricar checkpoint ou preencher datas.
6. Conferir SEM gravar:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    C:\Automacao\scripts\database\sync_link_catalog.py
```

7. Rever cobertura e datas: pode haver menos de 88 observacoes confirmadas.
   banco_links_com_coleta_explicita mostra quantos receberam evidencia real;
   coletados antigos nao sao dados recentes apenas porque o CLI os processou.
8. Congelar copia PROTEGIDA do checkpoint no E:, conferir usando --publication.
9. Apenas depois --apply --expected-digest na mesma copia revisada. Conferir
   novamente sem apply: links_pendentes_desta_publicacao=0 e digest processado.
10. Criar instance/operational-postgres-links-shadow.json com enabled=true.
    Nao modifica flags de outras fontes; nao precisa reiniciar para reler flag.
11. Executar NOVA verificacao. Conferir sem --apply: datas reais de coleta devem
    avancar, marcadores dos links novos processados e conteudo_ja_sincronizado=True.
    Novo capturado_em sozinho NAO comprova atualizacao automatica.

Nenhuma leitura de tela mudou para SQL. Leitor tecnico nao substitui autorizacao
AD; futuras consultas devem aplicar escopo no backend. Testes locais simulam
transporte e SQL, usam JSON em pastas temporarias e executam as funcoes de
coleta isoladas via AST. Nao consultam producao; SQL real ainda requer operador.
