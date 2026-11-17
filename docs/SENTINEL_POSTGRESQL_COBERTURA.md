# Cobertura e proximas etapas de persistencia

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
| Monitor de Admins | output/dashboard_admins_cache.json | Nao migrado |
| Baseline aprovada | fortianalyzer.admin_baseline_file em environment.json, padrao admin_baseline.json | Nao migrada |
| Contatos e papeis regionais | email_contatos.xlsx_path / sheet_name, planilha externa do SLA | Nao migrados |
| Maquinas virtuais | gerenciar_vms.py / data/vms.json | Sem migracao especifica; nao confundir com servidores cadastrados |
| Replicacao AD | data/replicacao.json e fonte publica escolhida pela rota | Sem migracao especifica |
| Certificados | certificate_disk_report_acrab.json | Sem migracao especifica |
| Metadados adicionais das regionais | estrutura_regionais.json | Nao considerar integralmente migrados so pela existencia da tabela regionais |
| Historicos, aprovacoes, notificacoes e relatorios | Fontes por modulo | Precisam levantamento proprio; sincronizar estado atual nao cria historico |

Esta lista e um levantamento do codigo, nao uma auditoria completa de todos
os arquivos da producao. Dados locais nao substituem conferencia do Rigel.
Senhas, tokens, certificados privados e vault DPAPI nao fazem parte da carga
de inventario nem devem aparecer em relatorios de auditoria.

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
