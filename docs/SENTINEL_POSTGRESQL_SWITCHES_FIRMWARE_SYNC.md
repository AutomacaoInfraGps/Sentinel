# Sincronizacao manual de firmware

## Estado e escopo

Carga 023 confirmada no Rigel: 1 fonte, 140 registros iguais a captura congelada;
137 candidatos concordantes e 3 pendencias, todos sem vinculos automaticos.
Digest inicial: 53a51969fd08a9c57231c1b75e9a28bf16bbc8a7422bb58acd5c5310764a72fb.
024 prepara somente sincronizacao manual. Nao ha worker, agendamento ou nova
consulta a equipamentos. Sentinel, Zabbix e jobs nao sao alterados.

## Sequencia no Rigel

1. Fazer novo pg_dump custom de sentinel em 127.0.0.1:5433, guardando em
   E:\Sentinel\PostgreSQL\backups. Deve conter a carga 023 confirmada; o backup
   anterior a essa carga nao a contem. Confirmar sucesso antes de migrar.
2. Aplicar scripts/database/sql/024_switch_firmware_sync.sql com psql -X,
   sentinel_admin, banco sentinel, porta 5433 e ON_ERROR_STOP=1.
3. Conferir inicialmente a captura da carga original, sem gravar:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\sync_switch_firmware_catalog.py' `
    --source 'E:\Sentinel\PostgreSQL\backups\carga-firmware-switches-20261119-073840-932\firmware-switches.json'
```

Esperado: 140 preservados/presentes, ultima_captura_sincronizada=null,
captura_mais_antiga=false, conflito_mesmo_horario=false e
conteudo_ja_sincronizado=false. A carga existe, mas o marcador ainda nao.

4. Apos revisar, repetir com --apply e --expected-digest com o digest inicial
   acima. Depois repetir a conferencia: conteudo_ja_sincronizado=true.
5. Preparar nova captura em pasta restrita usando
   capture_switch_firmware_catalog.py --output CAMINHO_NOVO. Revisar o resumo
   e o novo digest, conferir e so entao aplicar. Nao sobrescrever a captura
   inicial, nao copiar SQLite inteiro com jobs/WAL e nao forcar coleta.

## Modelo e protecoes

024 retira a unicidade fonte/ordem, mantendo fonte/host como chave. Assim uma
nova lista pode reutilizar posicoes sem colidir com registros ausentes
preservados. Ordem nao e identidade. Adiciona presente_na_captura e atualizado_em
e cria sincronizacoes_firmware_switches. Nao altera a evidencia original em
fontes_firmware_switches. O CHECK vinculo_confirmado=false continua ativo.
Collector recebe UPDATE no inventario e SELECT/INSERT/UPDATE no marcador;
nao recebe DELETE. Leitura continua no papel dedicado sentinel_firmware_reader,
sem grants gerais para API/DBeaver. Nao reiniciar PostgreSQL ou o aplicativo.

O comando exige --source, formato/digests validos, RIGEL e identidade SQL
sentinel_collector no banco sentinel/5433. Sem --apply apenas consulta em
transacao readonly. A escrita exige --expected-digest exato, mesmo advisory
lock da carga inicial, transacao, parametros e conferencia tipada completa
antes do commit. Sucesso somente e emitido apos o commit. Nao rele fontes vivas.

Captura anterior a carga inicial/ultimo marcador e bloqueada, assim como
digest diferente no mesmo horario. Nova exportacao nao autoriza regredir
consulta por host ou trocar metadados da mesma consulta declarada. Diagnostico
de correspondencia e ordem podem mudar, pois dependem do cache/lista e nao de
medicao nova. Repeticao retorna ja_sincronizado somente se marcador E todos os
campos das linhas presentes conferirem. Antes do primeiro sync, o hash do
inventario SQL e comparado a evidencia inicial.

Linhas fora da captura ficam presente_na_captura=false, sem exclusao. Isso nao
comprova remocao do equipamento. Mudancas de host/IP nao sao reconciliadas por
nome ou regional. Os tres casos pendentes permanecem sem correcao automatica.
Nao ha historico completo de cada revisao, apenas preservacao de ausentes;
backup/captura anteriores devem ser mantidos. Horarios SQL nao sao horarios de
coleta. checked_at_utc e declaracao legada, nao prova de atualizacao executada.

Apos futuros syncs, usar sync_switch_firmware_catalog.py para conferir capturas
atuais. import_switch_firmware_catalog.py continua inicial-only; sua conferencia
contra a origem inicial pode divergir legitimamente depois de atualizacoes.

## Conferencia administrativa

Usar sentinel_admin se o DBeaver de leitura nao tiver o papel dedicado.

```sql
SELECT count(*) AS preservados,
       count(*) FILTER (WHERE presente_na_captura) AS presentes,
       count(*) FILTER (WHERE vinculo_confirmado) AS vinculos_confirmados
FROM operacional.inventario_firmware_switches;

SELECT capturado_em, registros, sincronizado_em
FROM operacional.sincronizacoes_firmware_switches;
```

Implementacao preparada e testada localmente. Aplicacao e sincronizacao 024
ainda aguardam resultados do Rigel; automatizacao e uma etapa posterior.
