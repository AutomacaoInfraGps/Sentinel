# Carga inicial declarada da Replicacao AD

## Escopo revisado

Auditoria no Rigel em 18/11/2026: mesmos 32 nomes completos nas fontes local
e publica. A local tem 35 linhas (3 Origem e 32 Destino), total declarado 34
e 2 erros operacionais. Publicacao local declarada 10:43:47.505532 sem fuso;
o servidor confirmou Brasilia. Isso nao comprova nova coleta AD.

Usar somente a fonte local data/replicacao.json nesta carga, com
--source-timezone America/Sao_Paulo explicito. Preservar o texto das datas
e a conversao UTC, sem chama-las de ultima replicacao bem-sucedida.
Campos contadores sao declarados: o parser pode ter usado percentual como
erros/falhas. Nao corrigi-los, nem calcular estado saudavel a partir deles.
Nao deduzir regional ou fundir controladores por nome curto.

## Tabelas e acesso

019_replication_catalog.sql cria fontes_replicacao_ad (hash, digest, fuso,
publicacao e totais declarados), observacoes_replicacao_ad (ordem e identidade
nome completo + secao) e erros_operacionais_replicacao_ad (ordem e mensagem).
As tres ficam no esquema operacional. Totais inconsistentes sao preservados,
nao usados como contagem fisica de linhas ou controladores.

Nomes e mensagens sao informacoes internas. O papel NOLOGIN
sentinel_replicacao_reader recebe SELECT, mas nao e concedido automaticamente
ao sentinel_api nem aos leitores gerais. O collector recebe SELECT e INSERT,
sem UPDATE/DELETE. Conferencias administrativas usam sentinel_admin. Decidir
acesso nominal ao DBeaver separadamente; nao ampliar privilegios por conveniencia.
Somente campos explicitamente projetados sao importados; propriedades extras
como credenciais nao fazem parte do modelo. Mensagens e detalhes declarados
sao retidos em tabelas restritas, nao exibidos no resumo ou nas falhas do CLI.

## Sequencia de producao

1. Backup pg_dump antes da migracao (usuario informou concluido).
2. Publicar todos os arquivos novos e executar simulacao:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\import_replication_catalog.py' `
    --source-timezone America/Sao_Paulo
```

3. Criar copia congelada de data/replicacao.json em pasta nova e restrita sob
E:\Sentinel\PostgreSQL\backups. Aplicar as ACLs do procedimento de backup
existente, sem acesso a usuarios gerais. Nao publicar o JSON no Git/chat.
Simular novamente com --source apontando a copia e revisar o digest.
4. Aplicar 019 via psql sentinel_admin, ON_ERROR_STOP=1, na instancia 5433.
5. Executar o mesmo comando da copia com --check-database. Exigir tabelas vazias.
6. Aplicar com --apply --expected-digest igual ao digest revisado, sem mudar
source ou source-timezone. Nao usar digest da auditoria: o digest_carga vincula
os bytes, fuso e projecao tipada.
7. Conferir contagens e secoes por SQL administrativo. Nao repetir a carga
inicial em tabelas preenchidas, mesmo se o cliente perder a resposta.

Default e simulacao sem conexao SQL. SQL exige source explicito e RIGEL.
A escrita usa transacao, lock consultivo exclusivo deste importador, tabelas
vazias, SQL parametrizado e leitura tipada integral antes do commit. Qualquer
falha deve cancelar a transacao. Sucesso e impresso apenas apos o commit.
O lock de tabela e ROW EXCLUSIVE, compativel com os privilegios INSERT do
collector; nao usar SHARE ROW EXCLUSIVE exigindo privilegios extras.

Formato legado publico, linhas sinteticas Problema, novos campos de coleta,
identidades repetidas, datas invalidas/ambiguas e status desconhecidos bloqueiam
a carga para revisao. Listas vazias nao substituem inventario existente.
Erro operacional pode existir junto a linhas OK: nao descartar nem sintetizar
um controlador adicional a partir da mensagem.

Sem sincronizacao automatica, mudancas no AD, repadmin, servicos ou leitores
web. Trata-se de um retrato declarado da fonte, nao de telemetria validada.
