# Sincronizacao paralela do cadastro e servidores

## Ponto de partida confirmado no Rigel

Em 16/11/2026, a carga inicial foi confirmada e sentinel_api leu 51 regionais,
76 servidores, 49 firewalls e 49 licencas. A migracao 002 ja foi aplicada.
Nao repetir carga inicial nem migracoes 001/002.

## Publicacao original preservada

GerenciadorRegionais.salvar_regionais ja atualiza
configuracao.ultima_atualizacao e grava estrutura_regionais.json com arquivo
temporario/os.replace. O hook roda SOMENTE depois desse salvamento bem-sucedido.
Excecao no hook nao reverte nem impede o JSON; erro no salvamento original nao
enfileira dados. Nao altera verificacoes, periodicidade, credenciais ou telas.
Nao modifica gerenciador_atualizacoes.py (arquivo do Rigel difere historicamente).

Este e um cadastro com observacoes persistidas. Publicar apos editar um nome,
um link ou uma regional nao significa que todos os servidores foram verificados.
A ultima verificacao de cada servidor continua independente da publicacao.

## Implementacao

- services/operational_server_postgres.py: whitelist tipada antes de digest/fila;
  nao enfileira senha, usuario, referencia DPAPI ou JSON bruto.
- scripts/database/sql/003_server_shadow_sync.sql: presenca no cadastro regional,
  presenca dos servidores, data de atualizacao SQL e marcador exclusivo da fonte.
- scripts/database/sync_server_catalog.py: conferencia padrao somente leitura;
  escrita manual somente --apply --expected-digest do snapshot revisado.
- instance/operational-postgres-servers-shadow.json: ativacao exclusiva de servidores.
  Ausente/invalido/booleano diferente de true significa desligado. O flag dos
  firewalls NAO habilita servidores. Exemplo versionado tem enabled=false.

A migracao acrescenta UPDATE em servidores, pois agora ha upsert e marcacao de
ausentes; esse privilegio tambem permite o lock forte usado na transacao. Nao
concede DELETE/TRUNCATE/MAINTAIN/CREATE. Mantem a conta de leitura SELECT-only.

O escritor trava regionais antes de servidores/marcador, em READ COMMITTED,
serializando com a carga inicial e com firewalls. Timeouts limitam espera; uma
falha aguarda outra publicacao normal. Nao ha retry infinito ou nova coleta.
O lock de regionais pode fazer uma publicacao paralela de firewalls/servidores
falhar por timeout; a ultima publicacao valida continua disponivel.

Upsert por regional/id. Removidos ficam ausentes, nunca apagados ou considerados
offline. Regionais ausentes do cadastro permanecem para preservar FKs e os
dados de outras fontes. presente_no_cadastro nao substitui autorizacao AD.
Cadastro nao vazio com zero servidores e aceito para remocao explicita; cadastro
sem nenhuma regional e recusado para nao limpar o estado por falha estrutural.

Publicacao antiga nao sobrescreve marcador recente. Mesmo horario com conteudo
diferente e erro. Mesmo digest nao regrava. Observacao individual antiga/NULL nao
substitui status/tempo/data ja conhecidos de observacao mais recente. Metadados
de cadastro (nome, IP, ativo etc.) continuam seguindo a nova publicacao.

O digest registra a publicacao processada, nao promete igualdade byte a byte
entre fonte e SQL: observacoes mais recentes ja no banco podem ser preservadas.
Datas ingenuas usam America/Sao_Paulo explicitamente e sao convertidas a UTC.
Nao se usa mtime nem horario de importacao para fingir observacao recente.

arquivo_origem_sha256 era o hash bruto da carga inicial. Para registros escritos
pelo sync fica NULL, pois nao ha arquivo congelado equivalente; nao se coloca
digest normalizado nesse campo. A procedencia da publicacao fica no marcador.
importado_em continua horario de primeiro cadastro SQL; atualizado_no_banco_em
registra o upsert, e ultima_verificacao continua observacao original.

Fila limitada (um pendente + um em execucao), com o algoritmo existente que
prefere publicacao mais recente. O payload e destacado antes de devolver o
controle ao chamador. Somente caminho canonico estrutura_regionais.json do
projeto e aceito pelo hook; fixtures e outras instancias nao sao fontes globais.
Logs usam codigo/SQLSTATE, nunca texto bruto do driver ou parametros.

## Implantacao controlada

1. Commit/push e pull. Manter flag de servidores ausente/desligado. Nao alterar
   o flag que ja habilita firewalls. Nenhuma SQL e executada pelo deploy Git.
2. Novo pg_dump custom de sentinel e pg_restore --list. Nao e teste de restauracao.
3. Executar somente 003 como sentinel_admin com psql -X e ON_ERROR_STOP=1.
   Migracao estrita: nao repetir depois de COMMIT.
4. Conferir com o CLI novo (sem gravacao) usando cadastro atual. A primeira
   conferencia deve mostrar marcador NULL e 76 servidores presentes, salvo
   mudancas reais de cadastro desde a carga inicial.

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    C:\Automacao\scripts\database\sync_server_catalog.py
```

5. Congelar copia PROTEGIDA do cadastro como na carga inicial (contem referencias
   de credenciais). Rodar CLI --source na copia, revisar data/contagens/digest e
   depois --apply --expected-digest. Repetir conferencia da MESMA copia.
6. Reiniciar Sentinel pelo restart_web_service.ps1 com flag desligado; conferir
   healthz/telas. Outros processos que importem gerenciar_regionais precisam
   recarregar o codigo pelo seu procedimento existente, nao iniciar duplicatas.
7. Criar flag de servidores enabled=true apos validacao. Nao precisa reiniciar
   para reler flag. Aguardar publicacao normal de salvar_regionais e conferir
   marcador/digest. Nao salvar cadastro manualmente so para simular uma coleta.

Credencial: mesma referencia DPAPI do coletor, mesma conta Windows autorizada a
le-la. Se um publicador rodar em outra identidade, nao ampliar ACL do cofre para
contornar: verificar o desenho operacional antes de habilitar nesse processo.

Desligar o flag evita novos envios e descarta pendentes, mas nao cancela uma
transacao em andamento. O JSON e os leitores existentes continuam funcionando.
Nao restaurar banco automaticamente nem remover colunas com processos ativos.

## Validacao e limites

Testes locais simulam cursor/driver e salvamento real em pasta temporaria;
incluem segredos fora da projecao, snapshots antigos, presenca, erros, marcador
final e falha SQL sem bloquear JSON. Nao ha PostgreSQL local para homologar a
migracao. SQL e comportamento reais ainda precisam da conferencia no Rigel.
Sem historico completo nem nova API AD. Rename/mudanca de regional cria nova
identidade, mantendo a anterior ausente. Fontes sobrescritas de forma concorrente
no JSON original nao sao reconciliadas por esta fila; o projeto preserva o
comportamento original e sincroniza as publicacoes que receber.
