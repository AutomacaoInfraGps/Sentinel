# Carga inicial de contatos SLA (014)

## Limite da mudanca

Espelhar os contatos da planilha existente no PostgreSQL. Nao substituir
gerenciar_contatos_email.py, nao trocar as rotas/leitores e nao alterar o
arquivo usado pelo projeto SLA. Nao ha sincronizacao automatica nesta etapa.
Nao ha alteracao em admins, baselines ou outras tabelas operacionais.

Os 38 rotulos regionais foram auditados no Rigel: 34 por identidade normalizada
e 4 aliases especificos confirmados contra o cache de firewalls. A simulacao
da copia real precisa confirmar essas contagens novamente. Referencia atual:
diretor 38, gerente 33, apoio_1 37 e apoio_2 19, total 127 vinculos preenchidos.
Isso nao significa 127 pessoas diferentes.

## Modelo e identidade

- fontes_contatos_sla: origem logica sentinel_sla_principal, aba real, hashes
  dos arquivos e digest tipado, alem do horario de importacao.
- regionais_contatos_sla: FK regional, rotulos SLA e FortiAnalyzer preservados,
  regra de vinculo e numero original da linha para rastreabilidade.
- contatos_regionais_sla: contato declarado por origem, regional e papel;
  nome_origem e email_origem preservam o texto nao vazio apos strip, como
  no leitor atual. Vazios e marcadores SEM_ nao viram pessoas ou e-mails.

Chave do vinculo e origem+regional+papel, nao posicao do Excel nem nome ou e-mail.
Papeis sem nome e sem e-mail nao geram linhas. Um papel preenchido parcialmente
e preservado e contado como lacuna. Mesmo nome/e-mail em varios papeis ou
regionais nao e fundido. Nao foi criado um cadastro mestre de pessoas com
identidades inventadas. Uma etapa futura pode reconciliar pessoas com uma
chave confiavel e regras de caixas compartilhadas aprovadas.

email_origem e o texto da celula, nao uma afirmacao de endereco unico valido
ou entregavel. Nao separar silenciosamente listas de destinatarios nem
normalizar a parte local do endereco. Ausencia na planilha nao e exclusao SQL.
Nao ha timestamp de coleta inventado para o cadastro: importado_em e somente
o horario de entrada no banco. A copia XLSX e seus hashes documentam a origem.

## Importador

scripts/database/import_sla_contacts.py, sem argumentos, simula usando somente
email_contatos.xlsx_path/sheet_name do environment.json e o catalogo regional
atual. Le configuracao bruta sem resolver credenciais, sem importar web_config,
sem SQL ou API no modo padrao. A saida tem apenas contagens, categorias e hashes.

Le XLSX em memoria, read_only, data_only=False, sem links externos e sem salvar.
Nao executa macros ou formulas. Aba configurada ausente, coluna obrigatoria
ausente/duplicada, formula, erro de celula ou valor nao textual bloqueiam a
carga. Nao troca de aba silenciosamente. Se nao houver aba configurada, a
simulacao usa a primeira como o leitor existente, mas copias exigem --sheet
com nome exato. Nomes, e-mails, aba e caminhos nao saem no resumo.

Valida regional por codigo/nome normalizado ou alias SLA verificado; nao usa
descricao geografica ou busca aproximada. Cada regional e cada rotulo de
origem precisa ser unico na carga. Destino ausente, vinculo ambiguo, repeticao
ou carga sem contatos bloqueiam sem gravar. Digest inclui ambos os arquivos,
origem logica, aba, codigos regionais e linhas tipadas.

Operacoes SQL exigem copias explicitas: --source arquivo.xlsx --sheet ABA
--regionals estrutura_regionais.json, somente no RIGEL, porta 5433 e banco
sentinel, usando sentinel_collector via DPAPI. --check-database e somente
leitura. --apply exige --expected-digest exato e as tres tabelas vazias.

Transacao adquire pg_try_advisory_xact_lock com chave fixa da carga SLA antes
de conferir tabelas vazias; outra carga cooperante e recusada sem espera.
O bloqueio e liberado automaticamente em commit/rollback. Advisory lock nao
impede SQL externo que nao siga o protocolo; PKs, FKs e a chave fixa da fonte
continuam protegendo a integridade. As tabelas sao bloqueadas na ordem
regionais (ACCESS SHARE), fontes, vinculos e contatos (ROW EXCLUSIVE).
Esses modos sao compativeis com SELECT/INSERT, sem conceder UPDATE ou MAINTAIN.
O bloqueio forte SHARE ROW EXCLUSIVE usado inicialmente era incompativel com
os grants da 014 e foi removido do importador apos erro 42501 no Rigel.
Nao reaplicar a 014: a correcao e apenas no Python. Conferir contagens antes
de repetir a carga com o importador atualizado. Confere
existencia de regionais antes de inserir. INSERTs parametrizados, sem UPDATE,
DELETE ou SQL arbitrario. Confere contagens e papeis antes do commit. Quem
abre a conexao controla commit/rollback; sucesso e impresso depois do commit.

## Privacidade e privilegios

014 cria sentinel_contatos_reader NOLOGIN, sem conceder esse papel a nenhum
login automaticamente. Tabelas pertencem a sentinel_owner. Leitor dedicado
tem USAGE no schema e SELECT nessas tres tabelas; coletor tem SELECT/INSERT.
Nao ha concessao de UPDATE/DELETE, acesso PUBLIC ou leitura nova para
sentinel_reader/sentinel_api. REVOKE explicito desses leitores protege tambem
contra concessoes diretas herdadas de default privileges usuais.

Isso nao anula privilegios de superusuarios, dono ou membros de outros papeis
administrativos. Revisar privilegios existentes e quem recebera o papel de
contatos antes de liberar DBeaver/SofIA/telas para esses dados. A migracao falha
se o papel ja existir: nao sobrescrever nem reutilizar papel desconhecido.
Escopo AD das telas nao e aplicado automaticamente em uma conexao SQL tecnica.

## Homologacao no Rigel

1. Publicar todos os arquivos e executar a simulacao sem argumentos.
2. Fazer backup custom-format de sentinel e verificar catalogo.
3. Congelar a planilha XLSX e o catalogo regional em pasta com ACL restrita,
   fechar edicao durante a copia e confirmar que o arquivo e valido. Nao
   divulgar a planilha com dados pessoais; nao incluir em Git.
4. Simular copias com --source, --sheet e --regionals; revisar digest e totais.
5. Aplicar somente 014_sla_contacts.sql como sentinel_admin com ON_ERROR_STOP;
   confirmar COMMIT. Fazer --check-database das mesmas copias.
6. Somente com tabelas vazias, regionais presentes e contagens revistas,
   aplicar --apply --expected-digest da copia aprovada.
7. Conferir contagens via admin ou conta explicitamente autorizada no papel
   de contatos. sentinel_api continuara sem SELECT dessas tabelas por padrao.
8. Nao repetir carga inicial em tabela ocupada. Depois planejar sincronizacao
   separada, com fonte de verdade, edicoes externas e falhas parciais definidas.

Testes locais cobrem XLSX sinteticos e mocks SQL, nao comprovam aplicacao
da migracao em PostgreSQL real. Nada nesta etapa modifica o projeto SLA.
