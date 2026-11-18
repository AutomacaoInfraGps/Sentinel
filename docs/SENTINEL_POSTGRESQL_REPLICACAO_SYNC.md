# Espelho opt-in da Replicacao AD

## Estado de producao

019 homologada no Rigel: 1 fonte, 35 linhas, 32 nomes completos distintos,
2 erros operacionais; 3 Origem e 32 Destino. A carga inicial usou a copia
restrita carga-replicacao-ad-20261118-105932-095/replicacao.json, com digest
dba750ad13944375516b0146456fe0dc18070d10ea5a9c5587ec54ce9cc12001.

020 e o worker estao preparados, ainda nao homologados/ativados no Rigel.
Nao repetir a carga inicial. Nao trocar a fonte de verdade da tela.

## Leitura, recibos e transacao

services/operational_replication.py le somente data/replicacao.json. Nao
consulta a fonte publica, nao segue a escolha dinamica da tela, nao executa
repadmin e nao altera o AD. Reutiliza a validacao tipada da carga inicial:
servidores nao vazio, secao explicita Origem/Destino, nome completo unico
por secao, status reconhecido, lista explicita de erros e datas validas.
Linhas sinteticas Problema e novos campos de coleta exigem revisao.

Contadores, totais divergentes e status sao declaracoes da fonte, nao
indicadores recalculados de saude. ultima_replicacao pode ser hora da coleta;
timestamp pode mudar ao republicar um cache antigo. Nem um novo hash nem
uma leitura recente comprovam nova consulta ou replicacao bem-sucedida.

O recibo output/replication_postgres_publication.json tem somente versao,
horario de captura, fuso e hashes. Nao inclui nomes, erros brutos, caminhos
ou credenciais. E substituido atomicamente apos leitura estavel. Sua carga
exige que a revisao da fonte atual ainda corresponda aos hashes: congelar
o recibo nao congela os dados, nem autoriza reproduzir revisoes antigas.
Se a fonte mudar, recapturar e revisar o novo digest, nao forcar aplicacao.
Na revalidacao de um recibo, o hash e conferido antes de comparar as datas
da fonte com a captura antiga. Uma publicacao mais nova deve ser diagnosticada
como fonte alterada, nao como relogio futuro. Datas posteriores a captura
continuam bloqueadas quando o hash corresponde ao recibo.

O digest normalizado vincula o caminho efetivo (em hash), fuso, bytes e
projecao tipada. A hora da captura nao altera o digest. O marcador lido_em
significa leitura do arquivo pelo espelho, nunca coleta AD.

Escrita protegida por lock de arquivo entre processos, lock consultivo
igual ao bootstrap e transacao SQL. Confere instancia/usuario, fuso inicial,
origem ja fixada no marcador, datas futuras e regressoes. Publicacao antiga
ou captura antiga e ignorada; mesmo horario com hash diferente bloqueia.
Revalida a fonte antes de escrever e antes de atualizar o marcador, confere
integralmente as linhas tipadas e so imprime sucesso depois do commit.
Falha de leitura, SQL, DPAPI ou validacao preserva o banco e o arquivo-fonte.

## Identidade e ausencia

020 troca a chave primaria das observacoes de fonte+ordem para
fonte+nome_identidade+secao. Ordem e posicao mutavel de exibicao. O indice
unico anterior de identidade e mantido, sem necessidade de adivinhar seu
nome gerado pelo PostgreSQL. Origem e Destino do mesmo nome seguem separados.

Observacoes e erros recebem presente_na_fonte. Linhas ausentes sao mantidas
com false, nao excluidas, e isso nao prova remocao do controlador do AD.
Mensagens sao identificadas pela posicao na lista da fonte, nao por uma
identidade permanente de incidente. Mensagens na mesma posicao podem ser
substituidas. Este espelho nao cria historico completo de incidentes ou
replicacoes; valores anteriores de linhas existentes tambem sao atualizados.

fontes_replicacao_ad passa a refletir os metadados da ultima fonte aceita;
digest_carga passa a conter o digest dessa revisao atual. O backup/copia
congelada preserva a evidencia da carga inicial. Consultas de estado atual
devem filtrar presente_na_fonte nas observacoes e erros. Contagens sem esse
filtro podem incluir linhas retidas de fontes anteriores.

## Ativacao controlada no Rigel

1. Fazer novo pg_dump antes de 020. Publicar os arquivos novos e fazer pull.
2. Aplicar scripts/database/sql/020_replication_shadow_sync.sql com
sentinel_admin, psql -X, ON_ERROR_STOP=1, banco sentinel porta 5433. Nao
executar a migracao novamente depois de confirmada.
3. Capturar sem conexao SQL:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\sync_replication_catalog.py' `
    --capture --source-timezone America/Sao_Paulo
```

4. Executar o CLI sem flags para conferir o recibo em modo somente leitura.
5. Copiar o recibo para arquivo novo restrito sob E:\Sentinel\PostgreSQL\backups,
reconferir com --publication e aplicar com --apply --expected-digest revisado.
O digest de sincronizacao NAO e o digest da carga inicial.
6. Conferir o mesmo recibo sem --apply e exigir conteudo_ja_sincronizado=true.
7. Criar, somente se ainda ausente, o arquivo local nao versionado
instance/operational-postgres-replication-shadow.json com:

```json
{"enabled":true,"source_timezone":"America/Sao_Paulo"}
```

8. Reiniciar somente o processo web pelo restart_web_service.ps1, para
carregar o novo worker. Nao reiniciar PostgreSQL. A conta Windows do worker
deve ser a mesma que tem acesso ao segredo DPAPI do collector.
9. Aguardar um ciclo (300 segundos), conferir o CLI sem flags e confirmar
lido_em novo e conteudo_ja_sincronizado=true. Conteudo igual pode manter o
mesmo digest. Isso valida o espelho, nao uma nova consulta AD.

O worker e iniciado por run_web_service.py em thread daemon independente das
requisicoes. So trabalha no RIGEL e com enabled=true. Arquivo ausente,
invalido ou enabled diferente de true desativa o polling. Nao criar o flag
antes de homologar a migracao e a aplicacao manual. Para desativar proximos
ciclos, definir enabled=false; isso nao desfaz transacoes ja concluidas.

## Permissoes e verificacao

O collector recebe UPDATE nas tres tabelas existentes e SELECT/INSERT/UPDATE
no marcador, sem DELETE. O marcador e visivel apenas ao leitor restrito
sentinel_replicacao_reader; nao ha concessao a sentinel_api/sentinel_reader.
Conferencias de producao usam sentinel_admin. Nao dar permissao ampla para
contornar o erro esperado 42501 da conexao geral de leitura do DBeaver.

```sql
SELECT count(*) AS linhas, count(DISTINCT nome_identidade) AS controladores
FROM operacional.observacoes_replicacao_ad WHERE presente_na_fonte;
SELECT secao, count(*) AS linhas FROM operacional.observacoes_replicacao_ad
WHERE presente_na_fonte GROUP BY secao ORDER BY secao;
SELECT count(*) AS erros_operacionais FROM operacional.erros_operacionais_replicacao_ad
WHERE presente_na_fonte;
SELECT lido_em, sincronizado_em FROM operacional.sincronizacoes_replicacao_ad;
```

Testes unitarios usam arquivos sinteticos e mocks SQL; nao substituem backup,
migracao e conferencia real no Rigel. Nao foi feita ativacao remota.
