# Carga inicial RF UniFi - migracao 027

## Pre-condicoes informadas no Rigel

Backup antes de RF: sentinel-antes-radios-unifi-20261119-152814-905.dump,
205895 bytes. Captura restrita em:
E:\Sentinel\PostgreSQL\backups\carga-radios-unifi-20261119-152903-923\radios-unifi.json.
Digest revisado dae75c115929e5e9bb6a20035b85f93cdffec2d9f0df742667aca2f828426e79.
216 APs em 39 sites, 453 configuracoes e 425 estatisticas; tx_retry ausente
em 16. Recebimento com fuso, medicao desconhecida, tabelas nao associadas.

Conferencia do destino enviada pelo operador: controladora encontrada e
endpoint concordante, zero sites/APs ausentes e zero APs com site divergente;
destino_compativel=true. Nenhum vinculo foi alterado. Nao comprova tabelas RF
criadas, carga feita ou RF atual: a captura continua sendo a revisada de 15:29:04.

## Modelo e acesso

027_unifi_radio_catalog.sql cria quatro tabelas novas, sem alterar tabelas de
inventario, coletores, telas ou flags. Transacao com validacao de banco sentinel,
porta 5433 e data_directory E:/Sentinel/PostgreSQL/data; falha cancela a migracao.

- fontes_radios_unifi: fonte/versao, controladora, endpoint de origem, horarios
  declarados e hashes. Preserva publicacao legada textual, sem inferir fuso.
- recebimentos_radios_unifi: MAC, site de origem, horario de recebimento, estado
  online declarado e situacao/quantidade de cada tabela. FK do AP e do site
  separadas: o site de origem e o da captura, nao um vinculo atual imutavel.
- configuracoes_radios_unifi: interface unica por AP, banda declarada e canal.
- estatisticas_radios_unifi: outra tabela independente, com interface, banda,
  canal e percentuais/situacoes. Nao ha FK de estatistica para configuracao.

Canal e escalar JSONB para preservar numero versus texto (incluindo auto e
zero); nao armazena objetos/payload arbitrario. Percentuais limitados a 0-100,
NULL distinto de zero e situacoes informado/ausente/nulo/invalido coerentes.
Medido_em e NULL, data_medicao_confirmada=false nesta versao. Recebimento nao
comprova medicao recente, inclusive quando o AP estava offline.

Papel dedicado sentinel_unifi_radios_reader NOLOGIN com USAGE/SELECT.
PUBLIC/sentinel_reader/sentinel_api nao recebem acesso automatico. Collector
recebe somente SELECT/INSERT nas novas tabelas, sem UPDATE/DELETE. Permissoes
existentes nas tabelas de inventario nao sao ampliadas. Nao conceder o reader
de RF a outros usuarios apenas para contornar um erro de acesso.

## Etapas no Rigel

Publicar codigo, fazer pull e aplicar apenas a migracao vazia:

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' `
    -X -h 127.0.0.1 -p 5433 `
    -U sentinel_admin -d sentinel -W `
    -v ON_ERROR_STOP=1 `
    --file='C:\Automacao\scripts\database\sql\027_unifi_radio_catalog.sql'
```

Conferir antes de gravar:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\import_ap_radio_catalog.py' `
    --source 'E:\Sentinel\PostgreSQL\backups\carga-radios-unifi-20261119-152903-923\radios-unifi.json' `
    --check-database
```

Esperado destino_compativel=true, quatro contagens zero,
tabelas_rf_vazias=true e conteudo_confere_com_captura=false. A antiga conferencia
de capture_ap_radio_catalog.py --check-database continua lendo apenas os vinculos
do inventario; usar o novo importador para conferir tambem as tabelas RF.

Somente depois de revisar esse resultado, executar import_ap_radio_catalog.py
com o mesmo --source, --apply e --expected-digest da captura acima.
Nao gerar um novo arquivo com o mesmo nome para contornar erros de digest/site.
Repetir --check-database apos carga: esperado 1 fonte, 216 recebimentos,
453 configuracoes, 425 estatisticas e conteudo_confere_com_captura=true.

Conferencia administrativa opcional (conta autorizada):

```sql
SELECT
 (SELECT count(*) FROM operacional.fontes_radios_unifi) AS fontes,
 (SELECT count(*) FROM operacional.recebimentos_radios_unifi) AS aps,
 (SELECT count(*) FROM operacional.configuracoes_radios_unifi) AS configuracoes,
 (SELECT count(*) FROM operacional.estatisticas_radios_unifi) AS estatisticas;
SELECT tx_retry_situacao, count(*) AS registros
FROM operacional.estatisticas_radios_unifi GROUP BY tx_retry_situacao;
```

## Controle transacional

Sem flag SQL, o novo importador simula somente a captura congelada. SQL exige
RIGEL; gravacao exige digest exato. Leitura dupla detecta alteracao do arquivo,
validacao da captura cobre todos os campos/identidades e hashes; recebimento
futuro ou captura futura nao e convertido para outra zona para passar.

Conferencia usa conexao default readonly e REPEATABLE READ, READ ONLY.
Gravacao usa READ COMMITTED, advisory lock proprio, locks SHARE curtos em
controladora/sites/APs (nessa ordem) e ROW EXCLUSIVE nas novas tabelas, com
timeout. Reconfere destino sob esses locks e exige todas as tabelas RF vazias.
Nao faz UPDATE/DELETE nem altera vinculos para aceitar uma captura antiga.
Se o inventario mudou legitimamente de site, parar e revisar a fonte/destino.

INSERTs parametrizados respeitam FK e origem. Conferencia final compara todas
as colunas tipadas da fonte, recebimentos e duas tabelas RF; qualquer diferenca
cancela a transacao. Sucesso impresso somente depois do commit. Uma segunda
carga inicial e recusada, inclusive se alguma tabela estiver populada parcialmente.

Nao ha sincronizacao automatica RF, historico continuo, exclusao por ausencia,
troca de leitores ou reinicio de PostgreSQL/web nesta etapa. Coletores/escritores
de inventario existentes continuam como estavam, sujeitos aos locks curtos.
SQLSTATE/tipo de falha podem ser exibidos; valores e mensagem bruta sao omitidos.
Testes locais sao sinteticos, sem PostgreSQL real ou conexao remota ao Rigel.
