# Sincronizacao manual dos metadados regionais

## Estado confirmado

025 aplicada no Rigel. Carga inicial conferida: 1 fonte, 51 metadados,
conteudo_confere_com_captura=true, zero codigos ausentes, nomes divergentes
ou regionais fora do cadastro principal. Captura restrita:
E:\Sentinel\PostgreSQL\backups\carga-metadados-regionais-20261119-094823-416\metadados-regionais.json.
Digest: bea18ab2136e8b825ff4aa863547ef7c66f48072e038670510e65571bb9c59ad.
sha256_metadados: aed53b775b365216945d7fa8ec83d018ac81756afbce97cd0d323056e0342b61.
Capturado em 2026-11-19T12:48:24.129727+00:00. Publicacao do cadastro sem fuso.

026 prepara apenas sincronizacao MANUAL de capturas congeladas. Nao cria
worker ou flag automatica, nao altera telas/JSON/SLA, cadastro principal ou
aliases regionais. Automatizacao sera etapa posterior, apos validar um novo
snapshot. A origem da carga inicial permanece preservada.

## Sequencia de producao

1. Fazer novo pg_dump custom de sentinel em 127.0.0.1:5433, sentinel_admin,
   para pasta restrita E:\Sentinel\PostgreSQL\backups. Esse backup deve conter
   a carga 025; o backup anterior a ela nao a contem. Confirmar antes de migrar.
2. Aplicar scripts/database/sql/026_regional_metadata_sync.sql com psql -X,
   ON_ERROR_STOP=1, sentinel_admin, banco sentinel e porta 5433.
3. Conferir a captura inicial somente leitura:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\sync_regional_metadata_catalog.py' `
    --source 'E:\Sentinel\PostgreSQL\backups\carga-metadados-regionais-20261119-094823-416\metadados-regionais.json'
```

Esperado: 51 metadados presentes/preservados, conteudo_atual_confere=true,
conteudo_ja_sincronizado=false e marcador null. Todas as flags de regressao,
conflito de horario/publicacao e incompatibilidade de fuso devem ser false;
contagens de divergencia do cadastro principal devem ser zero.

4. Apos revisar, aplicar esse mesmo --source com --apply --expected-digest
   bea18ab2136e8b825ff4aa863547ef7c66f48072e038670510e65571bb9c59ad.
5. Repetir conferencia: conteudo_ja_sincronizado=true, marcador preenchido.
6. Capturar nova projecao com import_regional_metadata_catalog.py --capture
   CAMINHO_NOVO em outra pasta restrita, revisar resumo/digest e repetir
   conferencia, apply com digest revisado e conferencia final. Nao reutilizar
   arquivo inicial, copiar cadastro com dispositivos ou provocar edicao de dados
   apenas para testar o escritor. Sem metadados novos, o marcador pode avancar
   sem regravar linhas.

## Modelo e seguranca

026 adiciona presente_na_captura e atualizado_em a metadados_regionais e cria
sincronizacoes_metadados_regionais. Nao altera a tabela principal regionais ou
a evidencia original em fontes_metadados_regionais. Mantem FK por codigo e
restricao estado/uf validos e concordantes. Nao e necessario reiniciar servicos.

Collector recebe UPDATE nos metadados e SELECT/INSERT/UPDATE no marcador;
sem DELETE. O novo marcador recebe somente o leitor dedicado
sentinel_regionais_metadados_reader, sem ampliar acesso da API ou leitores
gerais. Descricoes podem conter endereco/informacao interna e nao sao logs.

O CLI exige --source congelado e validado, arquivo estavel, RIGEL, identidade
collector no banco sentinel/5433. Sem --apply, transacao readonly. Gravacao
exige digest exato, advisory lock compartilhado com carga inicial, SHARE curto
em regionais para impedir alteracao concorrente, parametros e conferencia
tipada de todas as linhas presentes e do marcador antes do commit. Sucesso
so e impresso apos commit; erros sao tratados sem dados brutos/credenciais.

Antes do primeiro sync, compara hash dos metadados SQL com a origem inicial.
Se algum codigo estiver ausente, nome divergir ou regional nao estiver presente
no cadastro principal, bloqueia sem renomear, cadastrar ou mudar vinculos.
Depois de edicoes legitimas no cadastro, aguardar/conferir o espelho principal
antes de sincronizar metadados dependentes. Nao contornar o bloqueio com grants.

Captura mais antiga ou digest diferente no mesmo horario e bloqueado. O
marcador tambem guarda publicacao textual, hash de metadados e hash da origem.
Nova captura de um cadastro antigo nao pode retroceder publicacao, nem trocar
metadados quando o horario de publicacao e igual. Mudancas de dispositivos
que nao alteram os cinco campos nao sao conflito de metadados.

Publicacao SEM fuso e ordenada somente no eixo de horario textual declarado,
nao convertida em instante UTC nem assumida como Brasilia. Publicacoes COM
fuso podem ser comparadas por seus instantes. Troca entre sem/com fuso bloqueia
ate revisao explicita, sem inferencia. Alteracoes manuais sem atualizar a
publicacao tambem exigem revisao; nao desabilitar esse controle silenciosamente.
Captura e data SQL nao comprovam coleta de equipamento ou data individual de
edicao de cada descricao/UF.

Metadados ausentes na nova captura sao preservados com presente_na_captura=false,
sem excluir a regional principal, aparelhos, pessoas ou contatos SLA. Isso
indica apenas ausencia na projecao, nao desativacao real. Nao ha historico
completo de revisoes por regional; manter capturas/backup anteriores.
Dados iguais atualizam so o marcador; repeticao exata retorna ja_sincronizado
somente se marcador, campos presentes e vinculos principais conferirem.

Apos futuras sincronizacoes usar sync_regional_metadata_catalog.py para conferir
capturas atuais. O importador inicial nao deve ser reaplicado; sua conferencia
contra evidencia inicial pode divergir legitimamente apos alteracoes.

## Conferencia administrativa

Usar sentinel_admin se a conexao DBeaver nao tiver o papel dedicado.

```sql
SELECT count(*) AS preservados,
       count(*) FILTER (WHERE presente_na_captura) AS presentes,
       count(*) FILTER (WHERE estado = uf) AS estado_uf_concordantes
FROM operacional.metadados_regionais;

SELECT capturado_em, regionais, sincronizado_em
FROM operacional.sincronizacoes_metadados_regionais;
```

Implementacao preparada e testada localmente. Migracao e sincronizacao 026
ainda aguardam execucao e resultados do Rigel.
