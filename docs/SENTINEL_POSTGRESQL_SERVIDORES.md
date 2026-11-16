# Carga inicial de regionais e servidores

## Escopo desta entrega

A auditoria do Rigel em 16/11/2026 informou 51 regionais, 76 servidores,
153 switches vinculados mais 13 sem vinculo, 88 links, 216 APs, 166 VPNs,
161 redes Wi-Fi vinculadas mais 26 sem vinculo, e 49 firewalls.
Sao quantidades observadas, nao constantes nem prova de coleta simultanea.

Esta etapa prepara o cadastro completo de regionais e a primeira tabela de
servidores. Nao migra ainda switches, links, APs, WLANs, VPNs, administradores,
eventos, historico ou configuracoes. Nao muda coletores, mapa, SofIA ou AD.

Fonte nativa: estrutura_regionais.json, nao o mapa derivado. Identidade do
servidor: codigo regional + id persistido na origem. IDs repetidos na mesma
regional bloqueiam a carga. Trocas futuras de regional exigem reconciliacao;
nao serao inferidas por nome/IP. Ausencia de timestamp nunca vira horario atual.

Campos gravados: identidade, nome/tipo, IP, modelo, funcao, sistema operacional,
status observado, ativo, ultima verificacao e tempo de resposta. Nenhum usuario,
senha, referencia DPAPI, erro bruto ou payload JSON completo e persistido.
O SHA-256 bruto identifica o arquivo revisado (nao e digest de publicacao).
importado_em registra a carga, nunca substitui ultima_verificacao.
O cadastro pode conter observacoes antigas; nao implica disponibilidade atual.

## Arquivos e guardas

- scripts/database/sql/002_server_catalog.sql: tabela nova, transacao/timeout,
  destino sentinel/5433/E:/Sentinel/PostgreSQL/data, owner sentinel_owner.
- scripts/database/import_server_catalog.py: simulacao padrao sem conexao;
  --check-database somente leitura; --apply exige hash exato revisado.
- Reutiliza localizacao temporal estrita do importador anterior; requer fuso
  explicito e rejeita horarios ambiguos/inexistentes.
- Collector recebe somente SELECT/INSERT na tabela nova; reader somente SELECT.
- Gravacao exige Rigel/identidade SQL fixa, trava regionais e servidores, recusa
  tabela de servidores nao vazia, insere na mesma transacao e confere contagens.
- Insere todas as regionais da origem e preenche apenas nomes SQL ainda NULL;
  nao remove regionais anteriores nem altera firewalls/licencas.
- Segredos/conexao via DPAPI existente; nao ha senha em argumentos ou ambiente.

## Procedimento controlado no Rigel

1. Commit/push e pull do codigo. Nao executar a migracao 001 novamente.
2. Simular no arquivo atual, sem banco:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    C:\Automacao\scripts\database\import_server_catalog.py `
    --source-timezone America/Sao_Paulo
```

3. Rever quantidades e ausencia de datas. Preparar backup pg_dump custom do banco
   e ler catalogo com pg_restore --list. Restauracao real continua tarefa separada.
4. Copia congelada da origem em area restrita. O cadastro contem referencias de
   credenciais e possivelmente outros dados privados: nao commitar, compartilhar
   ou copiar para pasta publica. Preferir os backups existentes restritos a admins
   e servico e conferir ACL antes de criar a copia. Nao abrir permissoes.
5. Rodar --source na copia congelada, revisar novamente e guardar seu SHA-256.
6. Executar 002_server_catalog.sql como sentinel_admin com psql -X e
   ON_ERROR_STOP=1. Nao repetir apos COMMIT; nao mascara esquema divergente.
7. Rodar --check-database com a mesma copia, conferir tabela nova vazia.
8. Somente depois --apply --expected-sha256 com o hash revisado e mesma copia.
9. Conferir contagens via sentinel_api. Nova carga inicial recusara tabela cheia.

Nenhuma dessas etapas foi executada no PostgreSQL real pela implementacao local.
O operador deve informar cada resultado antes de avancar; nao aplicar tudo em
um bloco unico. Falha durante commit exige conferir antes de repetir.

## Correcao do bloqueio na primeira tentativa

O operador informou COMMIT da migracao 002 e conferencia com 49 regionais e zero
servidores; a primeira gravacao retornou erro generico. A revisao identificou
um defeito: SHARE ROW EXCLUSIVE em servidores exige mais que SELECT/INSERT.
O erro especifico dessa execucao nao foi capturado, portanto conferir contagens
antes de repetir. Nao conceder UPDATE, MAINTAIN, DELETE ou TRUNCATE para contornar.

O importador corrigido serializa suas execucoes pelo SHARE ROW EXCLUSIVE em
regionais (onde o coletor ja tem UPDATE) e usa ROW EXCLUSIVE em servidores,
compativel com INSERT. Outros escritores de servidores ainda nao existem nesta
etapa; a futura sincronizacao devera coordenar sua escrita pelo mesmo protocolo.
O bloqueio de servidores isoladamente nao exclui escritores externos que ignorem
esse protocolo. Falhas SQL agora informam etapa/tipo/SQLSTATE, nunca valores.
Nao repetir 002 nem alterar grants. A sintaxe/permissoes foram conferidas na
[documentacao PostgreSQL 18 de LOCK](https://www.postgresql.org/docs/18/sql-lock.html).

## Depois da primeira carga

A sincronizacao automatica de servidores NAO esta implementada aqui. Examinar
salvar_regionais e as publicacoes de verificacao, incluindo frequencia, processos
concorrentes e origem dos horarios, antes de adicionar o hook por fonte.
Precisaremos preservar itens removidos, impedir publicacoes antigas e tratar
falha parcial sem assumir offline, como na gravacao de firewalls.
Leituras futuras usam sentinel_api e escopo AD validado, nunca a lista enviada
livremente pelo cliente. A tabela e um cadastro inicial, nao uma API autorizada.
