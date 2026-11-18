# Extensao cadastral: tipo de monitoramento

## Evidencia e escopo

Auditoria Rigel 18/11/2026: 76 servidores por ID exato na regional, sem
duplicidades. Cadastro 71 online/5 offline, cache 73 online/3 offline;
2 status e 69 tempos de resposta divergentes apesar de ultima_verificacao
igual. Nao escolher automaticamente o cache como estado correto.

SQL confirmou 76 presentes, 70 com SO e 76 com verificacao, 71 online/5 offline.
Marcador cadastro_publicado_em=2026-11-18 14:54:40.028542-03,
sincronizado_em=2026-11-18 14:54:40.519526-03. Isso comprova alinhamento do
cadastro observado, nao nova consulta dos equipamentos.

tipo_monitoramento esta preenchido nos 76 registros mas nao estava na
projecao SQL. 022 acrescenta somente essa coluna varchar(120) nullable,
sem DEFAULT, preenchimento automatico ou novas permissoes. Ausencia vira NULL;
texto e validado/trimado, sem inferir de tipo, SO, IP ou metodo de conexao.
Erros, manutencao, descricao do cache e hardware continuam pendentes.

## Compatibilidade de hashes

O bootstrap build_catalog continua com tuplas de 12 campos por padrao.
include_monitoring_type=True e opcao interna do escritor v2, com o campo
acrescentado no fim. Nao repetir o bootstrap nem modificar 002/003 aplicadas.

O digest v2 vincula versao, publicacao, regionais e nova projecao. Calcula
tambem em memoria o hash exato da projecao anterior. No mesmo horario, aceita
transicao apenas se o marcador SQL corresponder exatamente a esse hash
anterior. Conflito generico ou alteracao de estado no mesmo horario continua
bloqueado; depois de v2, mudanca de metadado no mesmo horario tambem bloqueia.
Nao adulterar a data do JSON para contornar validacao.

Escrita mantem locks/transacao existentes, preservacao por ultima_verificacao,
SQL parametrizado e ausencia sem DELETE. Confere integralmente
regional+ID+tipo_monitoramento antes do marcador. Inspecao somente leitura
mostra quantidade preenchida, igualdade dos pares e compatibilidade legada.
Credenciais continuam excluidas da projecao e dos resumos.

## Homologacao controlada

022 e o escritor v2 estao preparados, nao homologados no Rigel.

1. Publicar arquivos e fazer pull sem reiniciar o web ainda.
2. Simular no Rigel, sem SQL/cofre e antes de aplicar 022:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\sync_server_catalog.py' --simulate
```

3. Fazer novo pg_dump. Criar copia restrita de estrutura_regionais.json sob
E:\Sentinel\PostgreSQL\backups (pode conter credenciais; nao enviar/versionar).
Simular com --source da copia --simulate e revisar sha256_normalizado v2.
4. Aplicar 022 via psql sentinel_admin -X -v ON_ERROR_STOP=1 na instancia 5433.
A migracao valida banco e data_directory. Nao repetir apos COMMIT.
5. Conferir copia com --source, sem --simulate/--apply. Exigir contagens
esperadas e verificar data/hash antes de gravar.
6. Aplicar copia com --apply --expected-digest revisado e reconferir. Se o
marcador ja avancou, recapturar/revisar; nao forcar regressao. O CLI aplica
a projecao da copia, sem exigir que o arquivo vivo continue identico.
7. Reiniciar somente o web apos 022 para carregar v2. Manter flag existente
operational-postgres-servers-shadow.json; nao cria-lo/sobrescreve-lo sozinho.
Integracao continua no salvamento do cadastro, nao em novo polling do cache.
8. Apos salvamento normal, conferir fonte atual sem --apply e exigir
conteudo_ja_sincronizado=true e tipo_monitoramento_confere=true.

O escritor novo exige 022; nao reiniciar processos com ele e espelho ativo
antes da migracao. Falha SQL e nao fatal ao JSON, mas impede espelhamento.
Nao executar versao antiga do CLI/worker depois de atualizar o marcador v2;
manter versao consistente por processo usando o restart normal do web.

```sql
SELECT count(*) AS presentes, count(tipo_monitoramento) AS com_tipo_monitoramento
FROM operacional.servidores WHERE presente_no_snapshot;
SELECT status, count(*) AS servidores FROM operacional.servidores
WHERE presente_no_snapshot GROUP BY status ORDER BY status;
```

Testes unitarios nao substituem SQL real. Leitores web, cache de estado,
hardware e credenciais nao foram alterados. Nao ha historico de hardware
nesses dois JSONs para carregar: futura coleta precisa evidencia propria.
