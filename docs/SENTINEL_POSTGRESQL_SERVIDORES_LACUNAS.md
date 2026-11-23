# Auditoria das lacunas da tela de Servidores

## Escopo

Somente leitura de estrutura_regionais.json e do grupo servidores em
output/sentinel_operational_state.json. Sem SQL, cofre, coletores, teste de
conectividade ou chamada a API de hardware. Nao importar web_config,
operational_state, gerenciadores ou config: esses modulos tem efeitos de
inicializacao e nao sao necessarios para examinar arquivos.

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\audit_server_sources.py'
```

Enviar somente o JSON resumido, nao os arquivos. O resumo nao inclui nomes,
IDs, regionais, enderecos, descricoes, erros brutos ou valores de credenciais.
Somente contabiliza campos de acesso ja presentes nos JSONs, sem resolver
referencias DPAPI. Hashes dos arquivos incluem todos os bytes, nao os valores
em texto. Duas leituras confirmam estabilidade de cada arquivo isoladamente;
as fontes nao representam uma transacao atomica conjunta.

## Campos e fontes existentes

002/003 e a projecao original de services/operational_server_postgres.py projetam id, nome, tipo,
ip, modelo, funcao, sistema_operacional, status, ativo, ultima_verificacao e
tempo_resposta do cadastro regional. O cadastro define identidade/existencia;
o escritor paralelo e disparado ao salvar esse cadastro. Nao concluir que
os registros do cache do mapa ja estejam automaticamente no PostgreSQL.

A auditoria declara cobertura de uma projecao do codigo, nao do banco real.
Nao consulta tabelas, privilegios ou marcadores SQL de producao. Conferir
posteriormente no banco, antes de planejar extensao ou troca de leitor.

Na home /servidores, registros operacionais frescos da regional podem ser
preferidos ao cadastro. No detalhe da regional, o JSON continua definindo os
servidores existentes e um operacional mais recente pode sobrepor somente
estado/resposta/erro/verificacao/manutencao/motivo. A rota usa ID e fallback
por IP; isso nao torna IP uma identidade de servidor aprovada para SQL.

O resumo compara IDs textuais exatos dentro da mesma regional. Identidades
normalizadas repetidas sao diagnosticadas, mas nao fundidas. IP apenas na
mesma regional e candidato nao aprovado; IP repetido ou ID/IP que apontam
registros diferentes ficam ambiguos. Nao escolher o primeiro candidato.
Contagens de divergencias entre pares por ID nao significam que o cache
seja mais novo/correto: a auditoria nao aplica TTL, prioridades temporais,
escopo AD por usuario ou a selecao efetiva da pagina.

False e zero sao valores presentes, nao campos vazios. Diferenca de valor
ausente para false/zero e uma divergencia declarada, nao uma alteracao SQL.
ultima_verificacao e evidenciada separadamente de coletado_em; updated_at
e horario de publicacao do cache e nao prova medicao de hardware.

## Hardware sob demanda

O botao de hardware em regional_detalhes.html chama a rota
/api/regional/.../servidor/.../hardware. Essa rota retorna hardware para a
tela; nao foi identificado um caminho de gravacao desse retorno no cadastro
ou no grupo servidores. Ausencia de hardware nesses JSONs nao significa
que o botao nunca coletou nem que todo historico esteja preservado em outro
arquivo. O legado servidores.json e relatorios de preventiva nao sao as
fontes auditadas desta tela nesta etapa.

Campos exibidos incluem sistema operacional, fabricante, modelo, memoria,
CPU, uptime, discos, Bitdefender, temperaturas e ventoinhas. A auditoria mede
presenca de alguns desses campos diretos e sob hardware, e a presenca de
details/detalhes, sem validar seu conteudo como medicao real. Nao interpreta
conteudo arbitrario desses objetos nem executa fallback de coleta local.

O codigo tem caminhos WinRM/WMI, SSH Linux, probe HTTP, Redfish/iDRAC/iLO,
SNMP e fallback local. Uma futura persistencia precisa registrar alvo,
metodo, sucesso/parcialidade, horario com fuso e origem real dos valores.
Nao usar sucesso de probe HTTP como comprovacao de CPU/memoria/discos;
nao atribuir inventario do host local a um alvo remoto. Campos ausentes ou
padroes N/A/false nao provam ausencia de software, componente ou falha.

## Proxima etapa

Revisar resultado do Rigel. Se nao houver hardware persistido, nao inventar
uma carga historica: preparar captura tipada no caminho de coleta real em
etapa propria, preservando leitura atual e controles de acesso. Definir
escopo dos campos extras de cadastro/estado separadamente do hardware.
A extensao cadastral tipo_monitoramento 022 foi homologada manualmente no
Rigel em 18/11/2026: 76 valores conferidos com a projecao v2. Automatismo
posterior ficou pendente por decisao do usuario. Ver
SENTINEL_POSTGRESQL_SERVIDORES_MONITORAMENTO.md. O resumo da auditoria reflete
a projecao atual do codigo, nao uma nova consulta ao banco. Leitor web inalterado.

## Evidencia recebida em 23/11/2026

Auditoria do Rigel fornecida pelo operador: 51 regionais, 76 servidores em cada
fonte e 76 pares por ID exato na regional, sem identidades repetidas ou IPs
invalidos. Cadastro declara 71 online/5 offline; cache declara 73 online/3 offline.
Ha 2 diferencas de status/erro e 69 de tempo_resposta, com ultima_verificacao
igual nos pares. Nenhum dos 76 registros tem coletado_em explicito; os horarios
de verificacao sao sem fuso. Cache tem updated_at nos 76, nao usado como coleta.

Fora da projecao SQL: cadastro tem 5 erros e nenhuma descricao/manutencao;
cache tem 3 erros, 76 descricoes e 76 campos em_manutencao presentes. Presenca
nao distingue true de false. Nenhuma fonte tem hardware/details/detalhes neste
recorte. Nao inferir que ha 76 manutencoes nem migrar cache como cadastro.

Codigo do mapa monta descricao usando funcao ou tipo e faz teste de conectividade
proprio para estado/resposta/erro, podendo manter ultima_verificacao copiada do
cadastro. Publicacao do mapa e updated_at nao corrigem essa falta de evidencia
individual de coleta. Isso explica por que igualdade de horario nao basta para
escolher automaticamente a fonte com mais servidores online.

## Detalhamento adicional somente leitura

O mesmo audit_server_sources.py agora acrescenta, sem novas flags:

- Tipos de cada campo extra: ausente, nulo, booleano_true/false, texto vazio ou
  preenchido, numero, lista e objeto. Valores arbitrarios nunca sao exportados.
- Contagem de descricoes iguais/diferentes de funcao ou tipo, sem exporta-las;
  igualdade nao prova autoria nem campo independente.
- Faixas de comprimento das mensagens de erro, sem seu conteudo. Essa auditoria
  nao aprova mensagens livres para importacao sem revisao de sensibilidade.
- Transicoes de manutencao cadastro/cache por tipo e de status usando somente
  vocabulario permitido; valores de status desconhecidos sao agrupados.
- Campos diferentes com horario textual valido de verificacao identico.

Executar novamente o comando do inicio e revisar os novos agregados antes de
definir uma captura/migracao. Fontes continuam independentes e sem snapshot
atomico; nenhuma prioridade temporal e inferida. Sem SQL, API, cofre, alteracao
de arquivo ou ativacao automatica nesta etapa.

## Resultado do detalhamento e evidencia de coleta preparada

Segunda auditoria do Rigel recebida em 23/11/2026 confirmou:

- 76 transicoes ausente -> booleano_false em em_manutencao. Nao ha 76
  manutencoes ativas; ausencia no cadastro continua diferente de false no cache.
- 76 descricoes iguais a funcao ou tipo, coerentes com a projecao do mapa.
- 5 erros textuais no cadastro e 3 no cache, todos ate 500 caracteres. Nao
  houve exposicao nem aprovacao de mensagens livres para uma carga SQL.
- 2 transicoes offline -> online e 72 tempos_resposta divergentes no cache,
  mantendo a mesma ultima_verificacao textual do cadastro.
- Hardware/details/detalhes e coletado_em ausentes em todos os registros.

A proxima etapa nao deve copiar esse cache sobre o cadastro. Foi preparada
instrumentacao do ping ja executado pelo mapa, sem adicionar requisicoes:

- verificar_vm_online(ip) preserva seu contrato booleano legado. O parametro
  opcional evidencia recebe campos tipados quando usado pelo mapa.
- Resposta positiva reconhecida ou tres respostas negativas reconhecidas
  registram coleta_status_confirmada=true, coleta_status_origem=icmp_ping e
  coletado_em UTC com fuso. Falha de alcance ICMP nao prova host desligado nem
  estado de VM/hipervisor, hardware, aplicacao ou servico.
- Excecao de execucao ou saida nao reconhecida nao confirma queda. Fica
  coleta_status_confirmada=false, coletado_em=NULL e erro_coleta_codigo fixo,
  sem incluir conteudo bruto de excecao nesse campo.
- O mapa usa esse marcador: em consulta confirmada, ultima_verificacao passa
  a representar o instante real, com offset local para os formatadores atuais;
  coletado_em permanece UTC. Nao converte horarios legados sem fuso.
- Sem IP ou com coleta inconclusiva, preserva status/ultima_verificacao do
  cadastro e nao reaproveita marcador true/coletado_em anterior como evidencia
  nova. Erro de coleta fica separado de resultado negativo de conectividade.
- tempo_resposta continua sendo duracao do teste completo, incluindo retries,
  e nao uma nova promessa de RTT ICMP ou medicao de hardware.

A projecao do mapa adiciona esses campos ao registro operacional. O cadastro
original e a projecao SQL existente nao sao alterados. A manutencao continua
uma camada separada, nao inferida do ping. Publicacao do cache, updated_at ou
mudanca de status por manutencao nao substituem a evidencia da consulta.

Depois de publicar/pull, combinar reinicio do web sem jobs/checklist ativos.
Atualizar o mapa pelo fluxo existente e aguardar a conclusao da coleta normal;
nao confundir a primeira resposta do cache antigo com resultado novo. Repetir
audit_server_sources.py: conferir coletado_em com_fuso, tipos de
coleta_status_confirmada, origem e erros de coleta. A auditoria continua sem
SQL/rede/cofre. Instrumentacao ainda nao homologada no Rigel.

Sem migracao SQL, carga ou ativacao de sincronizador nesta etapa. Hardware e
mensagens livres exigem tratamento proprio; nenhum historico anterior e
fabricado para preencher os novos campos.

## Conectividade compartilhada e custo de consulta (23/11/2026)

Esta etapa substitui o procedimento acima de disparar pings pelo mapa.
Preparada localmente; ainda precisa de homologacao no Rigel.

- `services/server_connectivity.py` publica observacoes ICMP atomicas em
  `output/server_connectivity/`. Um arquivo por endereco normalizado, com nome
  SHA-256, somente campos operacionais: sem senha, ID de cadastro ou hardware.
  Compartilhar alcance do mesmo IP nao funde identidades de servidores.
- Pool com ate cinco testes simultaneos por processo web/CLI. Trava por alvo
  entre processos e reaproveitamento de tentativa com menos de 30 segundos,
  inclusive inconclusiva, evitam repetir ping em cliques sobrepostos.
  Nao e limite global de cinco entre varias instancias do aplicativo.
- Preservados os tres pings e timeouts de 3000 ms/5 s do verificador existente.
  Nao foi medida latencia de producao nem prometido tempo total. O tempo salvo
  continua sendo duracao do teste, nao RTT. Consultas de hardware sao separadas.
- Botao geral de Regionais, teste individual e rota legada `/verificar` usam
  a mesma conectividade ICMP. A rota legada deixa de testar HTTP/porta 443 como
  criterio de conectividade; diagnosticos especializados do verificador V2
  continuam disponiveis fora dessa rota.
- Respostas permanecem no contrato HTTP existente: o navegador aguarda cada
  regional, com servidores dessa regional em paralelo. Nao ha novo job duravel,
  nem retomada apos reinicio. Nao reiniciar enquanto uma verificacao estiver ativa.
- Mapa/fluxo neural, cards e dashboard de servidores leem a observacao sem
  disparar ping. Reconciliacao de cache do mapa nao renova sua data global nem
  medições dos demais equipamentos. O arquivo antigo em disco so muda quando
  a montagem/publicacao normal do mapa terminar; a resposta web aplica overlay.
- `conectividade_desatualizada` indica observacao acima de 300 segundos ou
  tentativa inconclusiva. Ler resultado antigo nao o transforma em coleta nova.
  Falha de execucao preserva ultimo estado/horario conhecido e marca tentativa
  nao confirmada. Manutencao/inatividade explicitas nao viram online pelo ping.
- O checklist completo usa a mesma observacao ICMP de ate 30 segundos nas duas
  etapas principais. Falha de coleta nao confirmada segue caminho de erro,
  nao confirma offline. Hardware, servicos e relatorios ainda podem fazer
  prechecks proprios; este patch nao paraleliza hardware nem altera credenciais.
- Testes rapidos nao regravam o cadastro nem acionam sincronizadores SQL por
  servidor. A projecao PostgreSQL atual continua cadastral: nao passa a ler o
  novo cache automaticamente. Corte SQL e leitores restantes ficam em etapa
  posterior, com auditoria e migracao especificas. Nao repetir cargas iniciais.

Validacao operacional: publicar/pull; reiniciar somente sem jobs ativos; testar
primeiro uma regional pequena pelo botao de servidores; abrir card, detalhe,
infra e mapa e comparar status/horario. Repetir em menos de 30 segundos deve
reaproveitar a mesma observacao. Apos 30 segundos, teste explicito deve produzir
nova tentativa. Abrir/recarregar mapa nao deve criar arquivos de observacao.
Conferir que uma regional com manutencao mantem sua camada de manutencao.
Depois testar todas as regionais e checklist em janela combinada. Nao executar
hardware ou checklist completo apenas para validar a leitura do mapa.
