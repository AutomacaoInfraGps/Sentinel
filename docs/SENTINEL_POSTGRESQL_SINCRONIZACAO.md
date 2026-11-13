# Gravacao paralela de firewalls e licencas

## Escopo

Primeira integracao do banco operacional do Rigel. Mantem as fontes, o coletor,
as frequencias, os arquivos atuais e as leituras de todas as telas e da SofIA.
Nao altera o gerenciador de atualizacoes nem implementa uma nova API de leitura.
A autorizacao AD continua no backend atual. Nao conceder acesso SQL ao agente.

O backup com a carga inicial informado pelo operador e:
`E:\Sentinel\PostgreSQL\backups\sentinel-antes-sync-20261113-082123-975.dump`.
Seu catalogo foi lido. Restauracao ainda nao foi testada.

## Arquivos

- `scripts/database/sql/001_firewall_shadow_sync.sql`: migracao transacional, uma vez.
- `services/operational_postgres.py`: projecao de colunas e worker de escrita.
- `scripts/database/sync_firewall_cache.py`: conferencia/manual, sem senha interativa.
- `web_config.py`: hook somente depois da gravacao do cache global de firewalls.
- `scripts/database/operational-postgres-shadow.example.json`: exemplo DESABILITADO.

O codigo web base foi conferido pelo operador com SHA-256
`7B3C9DE8811FC4AEAFCED94A0F52C25A842C28D443A4E5B2512C350784BAD2A3`.
O gerenciador do Rigel difere do local; NAO substituir esse arquivo.
Nao copiar a arvore inteira do projeto sobre producao.

SHA-256 da copia local atualizada do web_config com somente o hook:
`37D49E18E4B751EE677DCCCA687FC668FC314D10DF2C7C2776441B41147760E4`.

## Validacoes ja informadas pelo operador

Em 13/11/2026, a migracao SQL terminou com COMMIT. O modulo e o CLI foram
transferidos para o Rigel. A atualizacao manual do snapshot
`E:\Sentinel\PostgreSQL\backups\firewalls-antes-sync-20261113-084141-640.json`
retornou `sincronizado`, com 49 regionais, 49 firewalls e 49 licencas.
O digest normalizado foi
`dd87cb945f191a4a024470aa161797969b5cb06fe318bebb81be738293885c22`.
Uma nova conferencia confirmou o mesmo digest, 49 firewalls/licencas presentes
e marcador `2026-11-13T07:25:17.134574-03:00`, equivalente a
`2026-11-13T10:25:17.134574+00:00`. Isso valida a escrita manual; nao comprova
deploy do hook, ativacao ou funcionamento automatico.

## 1. Preparar o esquema, sem habilitar integracao

Transferir somente o arquivo SQL para o mesmo caminho relativo no Rigel e usar
`psql -X -h 127.0.0.1 -p 5433 -U sentinel_admin -d sentinel -W -v ON_ERROR_STOP=1 --file=...`.
A migracao confere banco, porta e data_directory antes do DDL. Cria o controle
da ultima publicacao, campos de presenca/procedencia e um indice unico de
licenca por firewall/nome/tipo, tratando NULLs como iguais.

Nenhum registro e apagado. Duplicidades existentes fazem a migracao falhar e
reverter, sem escolher silenciosamente qual registro manter. Nao repetir o SQL
se ja houve COMMIT: o arquivo e deliberadamente estrito, nao mascara divergencias
com IF NOT EXISTS. Falhas interrompem a sessao batch e revertem a transacao.

## 2. Conferir manualmente a nova persistencia

Transferir o modulo `services/operational_postgres.py` e o CLI
`scripts/database/sync_firewall_cache.py`, sem instalar ainda o web_config novo.
Executar como `GALAXIA\admin.pimentel` no `.venv31410`:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' C:\Automacao\scripts\database\sync_firewall_cache.py
```

O padrao abre transacao somente leitura. O hash normalizado nao e o hash bruto
do importador inicial: considera somente as colunas operacionais permitidas e
a data de publicacao. Ignora payloads e campos privados que nao serao gravados.
Nao existe modo de passar usuario SQL, host ou senha pelo prompt do agente.

Antes da primeira escrita manual, congelar uma copia do cache atual, conferir
com `--cache`, revisar contagens/data/hash e entao usar `--apply --expected-digest`
com esse hash normalizado. A credencial vem do DPAPI; nao pede senha.

A escrita usa UPDATE/INSERT na mesma transacao e so publica o marcador ao final.
Confere contagens de firewalls/licencas presentes. Uma falha anterior ao commit
reverte os registros; sequencias podem avancar. Se houver interrupcao durante
commit, conferir `operacional.sincronizacoes` e contagens antes de repetir.

## 3. Deploy do hook e ativacao separados

Somente depois da validacao manual, guardar uma copia do web_config do Rigel,
conferir que seu hash ainda e o baseline e transferir a copia atualizada.
Reiniciar pelo procedimento existente do Sentinel, nao iniciar um segundo web
server nem substituir o gerenciador. Nao ha reinicio automatico neste pacote.

A integracao fica desligada se `instance/operational-postgres-shadow.json`
estiver ausente, invalido ou nao contiver o booleano `"enabled": true`.
O exemplo tem false. Instalar o hook primeiro com a integracao DESABILITADA.
Testar o funcionamento normal do site antes da ativacao controlada.

O arquivo e relido nas publicacoes; nao e preciso reiniciar para ligar/desligar
depois que o hook estiver carregado. Desligar evita novos envios e descarta itens
pendentes, mas nao cancela uma transacao que ja estiver em andamento.

Ao ativar, observar uma coleta normal; comparar a publicacao do cache com
`operacional.sincronizacoes`, contagens presentes e logs. Nao adicionar um novo
agendamento de coleta ou mudar a periodicidade do gerenciador.

## Comportamento e limites

- Cache JSON e salvo primeiro; falha SQL nao impede a gravacao original.
- Fila em memoria limitada a um snapshot pendente, alem de um em execucao.
- Prefere a publicacao de data mais recente, nao necessariamente a ultima chegada.
- Publicacoes antigas nao sobrescrevem uma publicacao mais recente no banco.
- Conteudo ja sincronizado nao e gravado novamente.
- Locks e conexoes tem timeout; nao ha retry infinito ou fila persistente.
- Uma falha SQL aguarda outra publicacao normal para nova tentativa. Nao altera
  a data da coleta para fingir atualizacao; o ultimo marcador permanece antigo.
- O worker usa o mesmo usuario Windows do processo, a referencia DPAPI existente,
  loopback:5433, banco sentinel e conta SQL sentinel_collector.
- Ausentes ficam com `presente_no_snapshot=false`, sem DELETE e sem virar offline.
- Futuras consultas de estado atual devem filtrar presenca e escopo AD, alem de
  indicar lacunas/atualidade. Nao usar contagem bruta de todas as linhas como ativos.
- `licencas_informadas` significa lista nao vazia no snapshot, nao validade ou
  disponibilidade confirmada do produto.
- Vencimentos desconhecidos continuam NULL. Dias recebidos sao observacoes,
  inclusive os estimados por fallbacks existentes; nao ha nova regra de alerta.
- Dados de licenca preservados pelo coletor guardam `dados_anteriores`, a data e
  o status da ultima coleta valida. Nao recebem a data da tentativa como se fossem novos.
- O esquema guarda o ultimo estado conhecido por identidade, nao historico completo.
- Mudancas no nome/tipo da licenca criam outra identidade; a anterior fica ausente.
- Logs de falha mostram somente codigo fixo e SQLSTATE validado, sem valores.
- Nenhuma leitura de mapa, abas ou SofIA passa para PostgreSQL nesta etapa.

## Reversao e verificacao

Primeiro desligar o flag. O caminho original permanece funcionando. Reverter
somente o web_config para o backup se houver problema no deploy; nao restaurar
automaticamente todo o banco nem remover colunas enquanto houver processos usando-as.
Nao apagar o cofre DPAPI ou mudar permissoes para resolver falhas de sincronizacao.

Os testes locais usam conexoes simuladas e execucao isolada do hook, sem importar
o Flask completo nem abrir o PostgreSQL de producao. A sintaxe SQL foi conferida
na [documentacao de indices](https://www.postgresql.org/docs/18/sql-createindex.html)
e de [INSERT/ON CONFLICT](https://www.postgresql.org/docs/18/sql-insert.html).
Nao ha PostgreSQL local para um teste real desta migracao; a aplicacao e a
conferencia controladas no Rigel ainda sao necessarias antes de ativar o hook.
