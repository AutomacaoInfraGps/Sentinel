# Codigos regionais dos alertas

O escopo do webhook usa `regional_access.normalize_regional_code`. O mapa pode
conter codigos de origem com espacos, como `REG_REGIONAL BELO HORIZONTE`. Uma
comparacao literal com `REG_REGIONAL_BELO_HORIZONTE` excluia esses alertas.

`map_alerts.py` agora exporta a mesma identidade usada pelas permissoes. O ID
do alerta continua derivado do codigo original do mapa para preservar o upsert.
Os nomes exibidos, cadastros, grupos AD e memoria nao sao renomeados.

## Migracao 009

Aplicar `sofia/database/migrations/009_canonical_alert_regionals.sql` como
administrador PostgreSQL, depois das migracoes 001-008. Antes, gerar um backup
com `pg_dump -Fc -U postgres -d sofia` e guarda-lo com acesso restrito: ele pode
conter historico de conversas. Nao versionar o backup.

A migracao e transacional e pode ser reaplicada. Ela:

- adiciona um normalizador SQL com a regra do Sentinel (maiusculas, espacos e
  hifens para underscore, remocao de &, underscores consecutivos unidos);
- preserva acentos, prefixos e demais caracteres, como a regra Python;
- atualiza os codigos existentes de origem sentinel e recalcula seus hashes;
- normaliza a entrada da sincronizacao e dos filtros de leitura;
- preserva IDs, quantidades, estados, horarios e privilegios existentes.

Nao executar somente um UPDATE avulso: a proxima sincronizacao antiga poderia
restaurar os codigos com espacos. A funcao de sincronizacao atualizada protege
o banco mesmo antes do deploy Python no Rigel.

Depois, aplicar `sofia/database/verify_canonical_regionals.sql`. A verificacao
e somente leitura, valida exemplos equivalentes a regra Python, confere os
registros existentes e chama as funcoes de consulta sob `sofia_runtime`.
Os dois indicadores de escrita/criacao devem permanecer falsos. A presenca do
AP depende de ele ainda estar ativo na hora da verificacao.

Por fim, implantar `map_alerts.py` no Rigel e validar uma nova consulta no n8n
com a regional canonica dentro de allowed_regionals. Conferir category e demais
filtros se o banco devolver o AP mas a ferramenta ainda retornar zero.

## Limites

Isto alinha identidades, nao copia toda a infraestrutura para o banco da SofIA.
Ela continua recebendo snapshots minimos de alertas. Nao acrescentar busca
parcial ou fuzzy na autorizacao. O nome livre de uma regional precisa ser
resolvido contra os codigos autorizados antes da consulta.
