# Cobertura e proximas etapas de persistencia

Auditoria por tela atualizada em 18/11/2026:
[SENTINEL_POSTGRESQL_AUDITORIA_TELAS_20261118.md](SENTINEL_POSTGRESQL_AUDITORIA_TELAS_20261118.md).
Inclui lacunas de campos nas telas ja espelhadas e bancos separados (SQLite e SofIA).

## Homologado no Rigel em 2026-11-17

As migracoes 001 a 013 e as conferencias de producao cobrem os dominios:
regionais (identidade/cadastro necessario aos dispositivos), firewalls e
licencas, servidores (cadastro), switches Zabbix, VPNs, links automaticos,
controladora/sites/APs UniFi e WLANs configuradas. Os escritores paralelos
foram validados por publicacoes novas sem --apply. Os leitores das telas
continuam nas fontes existentes. Isso NAO equivale a migracao integral de
todos os campos, historico e funcionalidades do Sentinel.

## Lacunas confirmadas pela leitura do codigo

| Dominio | Fonte atual | Situacao PostgreSQL operacional |
| --- | --- | --- |
| Monitor de Admins | output/dashboard_admins_cache.json | 016/017 homologadas: 54 dispositivos, 227 contas observadas; nova leitura automatica em 18/11/2026 08:20:34 -03:00 |
| Baseline aprovada | fortianalyzer.admin_baseline_file em environment.json, padrao admin_baseline.json | 233 contas aprovadas separadas das observacoes; espelho 017 automatico confirmado, sem mudanca da baseline |
| Contatos e papeis regionais | email_contatos.xlsx_path / sheet_name, planilha externa do SLA | 014/015 homologadas; 38 regionais e 127 vinculos; nova leitura automatica confirmada em 18/11/2026 07:16:39 -03:00 |
| Maquinas virtuais | gerenciar_vms.py / data/vms.json | 018 homologada: 1 VM RJ, status declarado Unknown e verificacao NULL; sem telemetria/credenciais, sincronizacao automatica ou fusao com servidores |
| Replicacao AD | data/replicacao.json e fonte publica escolhida pela rota | 019/020 homologadas: 1 fonte, 35 linhas (3 Origem, 32 Destino), 32 controladores e 2 erros operacionais; nova leitura automatica confirmada em 18/11/2026 11:38:38 -03:00; leitor web inalterado |
| Certificados | certificate_disk_report_acrab.json | 021 homologada: 1 fonte e 3 thumbprints distintos; origem/coleta nao confirmadas preservadas como false/NULL; sem sincronizacao ou troca do leitor web |
| Campos adicionais de Servidores | cadastro regional, grupo servidores do cache e retorno de hardware sob demanda | 022 validada manualmente: 76 tipos de monitoramento conferem com fonte v2; automatismo posterior pendente por decisao do usuario. Estado extra/cache/hardware seguem pendentes |
| Campos adicionais de Switches | cache de status, cache operacional, metadados e inventario firmware SQLite | Rigel: mesmos 166 IDs nos caches e 166 presentes no SQL, 26 sem regional, todos online. Firmware 023/024: 140 presentes, 137 candidatos e 3 pendencias sem vinculos. Worker ativado e recorrencia confirmada em 19/11/2026, commits as 08:35:41 e 08:40:43 -03:00; sem consulta de equipamentos/jobs. Demais campos extras continuam pendentes |
| Metadados adicionais das regionais | estrutura_regionais.json | 025/026 confirmadas no Rigel: 51 presentes, descricoes e estado/uf concordantes e zero divergencias. Worker opt-in ativado, com commits confirmados em 19/11/2026 11:09:39 e 14:49:55 -03:00; conferencia --current as 14:50:20 -03:00 com conteudo_atual_confere=true e nenhum conflito. Recorrencia confirmada pelos ciclos observados, sem inferencia de UF ou alteracao de vinculos/SLA |
| Campos de radio dos APs | interferencia_5ghz_por_site e extensao radios_nativos em data/unifi.json | Auditoria legada informada no Rigel em 19/11/2026: 125 linhas RF, 31 sites e 102 grupos de canais, sem identidade/data de radio ou zeros comprovados; 91 dos 216 APs sem linha RF, sem inferir ausencia. Extensao nativa implementada nas duas versoes do coletor, preservando legado e espelho SQL atual, sem requisicoes adicionais. Publicacao/coleta e auditoria nativa no Rigel pendentes; nenhuma carga SQL RF |
| Historicos, aprovacoes, notificacoes e relatorios | Fontes por modulo | Precisam levantamento proprio; sincronizar estado atual nao cria historico |

Esta lista e um levantamento do codigo, nao uma auditoria completa de todos
os arquivos da producao. Dados locais nao substituem conferencia do Rigel.
Senhas, tokens, certificados privados e vault DPAPI nao fazem parte da carga
de inventario nem devem aparecer em relatorios de auditoria.

Auditoria RF e limites da projecao legada:
[SENTINEL_POSTGRESQL_APS_RADIOS_AUDITORIA.md](SENTINEL_POSTGRESQL_APS_RADIOS_AUDITORIA.md).

## Auditoria administrativa inicial

Executar scripts/database/audit_administrative_sources.py no Rigel com o
Python do Sentinel. Somente leitura, sem SQL, APIs de equipamentos, DPAPI,
edicao de planilha ou importacao de web_config. Usa caminhos configurados,
nao adivinha o local da planilha. Saida contem apenas contagens e categorias;
nomes, contas, e-mails, caminhos, motivos brutos e credenciais nao sao exibidos.

Com --unresolved, o relatorio acrescenta apenas rotulos regionais externos,
chaves/nomes de equipamentos sem vinculo unico e chaves de baseline fora do
cache. Nao exporta nomes de pessoas, e-mails, contas aprovadas/observadas ou
motivos brutos. A opcao nao aprova vinculos nem altera fontes; os rotulos
devem ser tratados como informacao interna. A ausencia no cache nao comprova
que um equipamento ou sua baseline deixou de existir.

Baseline e lista observada sao conjuntos distintos. Conta encontrada nunca
e aprovada automaticamente. Falha de consulta preserva conhecimento anterior,
nao prova ausencia, exclusao ou baseline vazia. Ha regras especificas de
visibilidade do FAZ e confirmacao de remocao em duas coletas validas no FGT;
essas regras precisam ser preservadas. O cache de FMG nem sempre declara
consulta_valida ou ultima_coleta_valida: ausencia deve continuar desconhecida.
Datas legadas sem fuso exigirao conversao explicita na etapa de importacao.

Para vinculos de administradores, a auditoria mede nome exato de firewall ja
catalogado (nao inventa serial a partir de nome). FMG/FAZ centrais nao recebem
uma regional arbitraria. Identidade definitiva precisa validacao de origem,
equipamento e escopo; apenas nome de usuario nao identifica conta global.

## Contatos: compatibilidade com o projeto SLA

gerenciar_contatos_email.py le a planilha com pandas e salva alteracoes nela
com openpyxl. Hoje a edicao do Sentinel tambem altera o arquivo usado pelo SLA.
Nao substituir essa fonte nem mudar o outro projeto durante uma carga SQL.
A auditoria abre o XLSX em modo read_only, fecha o arquivo sem salvar e exige
colunas unicas. Aba configurada ausente bloqueia a auditoria (nao troca de aba
silenciosamente). Formulas nas colunas de contatos exigem revisao; nao usa
valores calculados em cache como identidades comprovadas.

Papeis encontrados no codigo: diretor, gerente, apoio_1 e apoio_2. Os nomes
externos NOME_REGIONAL e NOME_REG_FORTI devem ser preservados como rotulos de
origem. _row_index e posicao mutavel da planilha, nao chave permanente SQL.
A auditoria sugere apenas candidatos unicos por codigo/nome normalizado,
sem descricao geografica, aproximacao ou primeiro candidato em empate.
Usa o normalizador existente de sites UniFi para os prefixos Vnnn, mas nao
aplica aliases de sites automaticamente a contatos. Todo vinculo e provisorio
ate conferencia. Nao fundir pessoas por nome, nem presumir que e-mail
compartilhado identifica uma unica pessoa.

Quatro aliases especificos do SLA foram conferidos no cache de firewalls do
Rigel: V024_REGIONAL_CEARA2 -> REG_CEARA_2,
V028_REGIONAL_CAMPINAS_BASE_2 -> REG_CAMPINAS_02,
V041_REGIONAL_CAXIAS_DO_SUL -> REG_CAXIAS e
V049_REGIONAL_MACAE01 -> REG_MACAE (nao REG_GRSA_MACAE).
services/sla_contact_matching.py exige tambem o rotulo FortiAnalyzer
correspondente e a existencia do destino no catalogo. Rotulo divergente ou
destino ausente fica pendente; nao ha fallback aproximado. Essas regras
nao alteram a planilha, a busca da tela, os aliases UniFi nem o escopo AD.
O relatorio discrimina alias_sla_verificado de identidade_normalizada_unica.

Modelo alvo a validar: cadastro de contatos, meios de contato e vinculos
contato-regional-papel, com origem e vigencia. Baseline e observacoes admins
em tabelas separadas, com evidencia de coleta e aprovacoes independentes.
Pessoas nao precisam de quatro copias por papel ou regional. A identidade de
pessoa e as regras para caixas compartilhadas dependem da auditoria real.

Sequencia: auditoria no Rigel, revisar identidades/vinculos, definir esquema
e permissoes, backup, copias restritas, simulacao com digest, migracao,
conferencia, carga e somente depois sincronizacao opt-in. Primeiro espelhar
as fontes existentes; uma troca de fonte de verdade precisa etapa propria,
considerando edicoes externas e que XLSX+PostgreSQL nao compartilham transacao.

Contatos e contas de administracao sao dados restritos. Nao conceder acesso
automaticamente a todos os leitores de inventario sem decidir quem pode ver
esses dominios. DBeaver com papel tecnico nao aplica o escopo AD das telas.
Em futuras consultas web/SofIA, o backend deve filtrar escopo do usuario antes
de retornar dados. Mudancas de autorizacao nao estao incluidas nesta auditoria.
