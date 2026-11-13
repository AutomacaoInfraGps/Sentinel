# PostgreSQL operacional do Sentinel

## Estado da preparacao no Rigel

Confirmado pelo operador em 12/11/2026:

- Servico: `postgresql-sentinel-18`, separado do Aegis.
- Dados: `E:\Sentinel\PostgreSQL\data`.
- Conexao local: `127.0.0.1:5433`, autenticacao SCRAM.
- Banco: `sentinel`; proprietario: `sentinel_owner` (`NOLOGIN`).
- Schema: `operacional`, pertencente a `sentinel_owner`.
- Tabelas criadas manualmente: `regionais`, `firewalls`, `licencas_firewall`.
- `sentinel_api` herda `sentinel_reader`: CONNECT, USAGE no schema e SELECT nas tres tabelas.
- `sentinel_collector`: CONNECT, USAGE no schema, SELECT/INSERT/UPDATE nas tres
  tabelas e USAGE nas duas sequencias de identidade. Sem DELETE concedido.

Este documento registra a preparacao manual; nao substitui uma verificacao do
catalogo no servidor nem e um script de migracao aplicado automaticamente.
Nenhuma tela, coletor ou conexao de producao foi alterada nesta etapa.
O banco `sofia` do Celeno e o banco operacional `sentinel` do Rigel sao distintos.

## Conferencia antes da primeira importacao

Disponibilize `scripts/database/audit_firewall_cache.py` no checkout do Rigel
pelo processo habitual de transferencia. A criacao do arquivo na maquina de
desenvolvimento nao o publica no servidor.

No PowerShell do Rigel, a partir de `C:\Automacao`, execute com um Python 3.10+
existente no servidor, por exemplo, se o comando `python` estiver disponivel:

```powershell
python .\scripts\database\audit_firewall_cache.py --cache 'C:\Automacao\output\dashboard_firewalls_cache.json'
```

O diagnostico usa somente a biblioteca padrao. Nao solicita senhas, nao conecta
ao PostgreSQL, nao grava arquivos e nao importa o aplicativo ou o cofre DPAPI.
A saida contem apenas contagens e categorias de problemas, sem seriais, IPs,
payloads ou credenciais. O escopo desta conferencia e administrativo; nao e uma
API de leitura para os usuarios da SofIA.

- Saida 0: nenhuma incompatibilidade estrutural encontrada; avisos ainda exigem revisao.
- Saida 1: inconsistencias nos dados; nao iniciar a importacao.
- Saida 2: falha de leitura ou formato; nao interpretar como inventario vazio.

Seriais duplicados sao comparados sem diferenciar maiusculas de minusculas.
Vencimentos ausentes sao lacunas, nao zero dias. Datas sem fuso sao sinalizadas,
nao convertidas usando silenciosamente o fuso desta maquina.
`estrutura_valida=true` nao e autorizacao para migrar nem confirma atualidade.

## Proximas etapas

1. Conferir o cache no Rigel e confirmar o fuso dos horarios sem offset.
2. Versionar o esquema efetivo e preparar importacao transacional com simulacao.
3. Testar autenticacao do coletor e configurar sua credencial com DPAPI na
   identidade Windows que realmente executara a integracao.
4. Fazer backup e testar restauracao antes da primeira gravacao controlada.
5. Importar sem mudar as leituras atuais e comparar dados e datas de coleta.
6. Somente depois integrar gravacao paralela aos mesmos coletores existentes.

Nao alterar frequencias, fontes, regras de alertas ou permissoes do Sentinel.
Nao conceder ao agente acesso SQL direto. A conta tecnica nao implementa as
permissoes regionais dos usuarios: a camada de consultas do Sentinel deve
continuar validando o login e o escopo autorizado em todas as leituras.

## Simulacao da carga inicial

O operador confirmou no Rigel: Windows `E. South America Standard Time`, Python
com offset `-03:00`, cache com 49 horarios locais sem fuso. O fuso de origem
declarado para interpretar esses horarios e `America/Sao_Paulo`, nao um offset
fixo. Horarios historicos ambiguos/inexistentes em mudancas de horario de verao
sao bloqueados. Instantes Unix sao sempre interpretados como UTC.

Backup informado pelo operador (catalogo lido, restauracao ainda nao testada):
`E:\Sentinel\PostgreSQL\backups\sentinel-antes-importacao-20261112-164101-114.dump`.
Esse dump do banco nao inclui a criacao das contas do cluster ou suas senhas.

Transfira tambem `scripts/database/import_firewall_cache.py` para a mesma pasta
do diagnostico no Rigel. Nao e necessario copiar testes ou atualizar o site.

```powershell
python C:\Automacao\scripts\database\import_firewall_cache.py --source-timezone America/Sao_Paulo
```

Sem `--apply`, o comando nao importa drivers SQL, nao pede senha e nao abre
conexao. Precisa de `tzdata` no Windows para resolver o nome IANA; se ausente,
pare e prepare um ambiente de migracao isolado, sem atualizar o runtime do site.
O comando nao gera arquivos nem modifica o cache. Guarde o resumo e o SHA-256.

A gravacao e uma etapa separada, nao liberada apenas por esta simulacao:

- Exige execucao no Rigel, `--apply` e `--expected-sha256` igual ao arquivo revisado.
- Usa Psycopg 3 (instalado separadamente) e senha SQL interativa oculta.
- Destino fixo: `127.0.0.1:5433`, banco `sentinel`, usuario `sentinel_collector`.
- Confere banco, usuario e porta na conexao antes de qualquer INSERT.
- Bloqueia escrita concorrente nas tres tabelas durante a transacao.
- Recusa a carga inteira se qualquer uma das tres tabelas ja contiver dados.
- Insere somente colunas operacionais explicitas, com parametros SQL.
- Nao usa DELETE, TRUNCATE, atualizacao de tabelas existentes ou DDL.
- Confere as tres contagens antes do commit; erro anterior ao commit reverte os registros.
- Uma interrupcao de conexao durante commit pode deixar resultado incerto: confira
  o banco antes de repetir. Sequencias podem avancar mesmo apos rollback.

Os nomes das regionais ficam NULL, pois o cache selecionado so fornece os codigos.
Dias restantes recebidos continuam sendo observacoes, inclusive nos fallbacks
sem data de vencimento; nao representam um prazo exato atualizado. Nao ha
recalculo nem mudanca de regra de alerta nesta importacao.

Este e um bootstrap das tres tabelas vazias, nao uma sincronizacao periodica.
Ele nao migra status de disponibilidade, historico, todas as regionais de outras
fontes ou demais recursos do Sentinel. As leituras do site continuam inalteradas.

Testes locais cobrem conversao de datas, simulacao, hash, protecao de destino,
parametrizacao e fluxo transacional com conexao simulada. A aplicacao real no
PostgreSQL do Rigel ainda precisa ser validada em etapa controlada.

Referencias: [Psycopg 3](https://www.psycopg.org/psycopg3/docs/basic/usage.html)
e [LOCK do PostgreSQL](https://www.postgresql.org/docs/18/sql-lock.html).

## Diagnostico apos falha de gravacao

A primeira tentativa de carga no Rigel retornou erro generico. Nao foi
confirmado commit nem identificada a causa; conferir contagens antes de repetir.
O snapshot revisado e
`E:\Sentinel\PostgreSQL\backups\firewalls-carga-inicial-20261112-165528-316.json`,
SHA-256 `8ac4b2b96522c6185eb75578b1d8aacec193b3d00bb843a009d97898c6a82f06`.

Atualize apenas `import_firewall_cache.py` no Rigel e execute:

```powershell
& 'E:\Sentinel\PostgreSQL\migration-venv\Scripts\python.exe' `
    C:\Automacao\scripts\database\import_firewall_cache.py `
    --cache 'E:\Sentinel\PostgreSQL\backups\firewalls-carga-inicial-20261112-165528-316.json' `
    --source-timezone America/Sao_Paulo `
    --check-database
```

Esse modo solicita a senha SQL de `sentinel_collector` e abre conexao local,
com transacao somente leitura. Confere a identidade de destino, conta as tres
tabelas e consulta as permissoes; nao executa INSERT, UPDATE, DELETE, DDL ou
LOCK explicito. Nao pode ser combinado com `--apply`.

Erros de banco/driver mostram somente a etapa interna, uma categoria permitida
e SQLSTATE validado (ou `indisponivel`), nunca a mensagem livre, parametros,
traceback ou senha. SQLSTATE ausente nao prova erro de autenticacao; pode ser
falha de conexao ou do cliente. Se as contagens nao forem zero, nao usar o
importador de carga inicial nem apagar registros para permitir sua repeticao.

Em 13/11/2026, o operador confirmou pelo `psql` que `sentinel_collector` conecta
na porta 5433, as tres contagens sao zero e o servico esta Running. Isso nao
confirma a causa da falha do Psycopg nem significa que a senha lida em todos os
clientes foi necessariamente identica. Nao redefinir senha nem ampliar grants
com base apenas em `OperationalError` sem SQLSTATE.

O diagnostico de conexao agora classifica algumas mensagens do libpq em memoria
e mostra somente um indicio fixo (autenticacao, rede, TLS, HBA, configuracao ou
protocolo), sem exibir a mensagem original. Se nao reconhecer, informa causa
ainda nao classificada. Os indicios nao sao diagnosticos definitivos.

O log Application/PostgreSQL do Rigel confirmou `password authentication failed`
para `sentinel_collector`, na regra SCRAM de loopback do diretorio Sentinel.
Ainda nao foi determinada a diferenca entre as entradas do `psql` e do Python.
Um caractere `$` digitado no prompt nao e, por si so, interpolado pelo PowerShell.

Para isolar a entrada interativa, `--check-database --password-stdin` aceita
somente uma string JSON UTF-8 pelo stdin. O chamador pode ler a senha com
`Read-Host -AsSecureString`, converter em memoria e envia-la por pipe anonimo.
Nao passar senha como argumento, variavel de ambiente, arquivo ou literal no
historico. A entrada por pipe nao altera a senha do banco.
O valor decodificado e preservado exatamente: nao ha trim nem interpolacao.
O cliente necessariamente materializa a senha em memoria para autenticar;
descartar referencias nao garante zeragem de strings imutaveis na memoria.

Referencias de entrada: [Read-Host](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/read-host?view=powershell-5.1)
e [getpass](https://docs.python.org/3/library/getpass.html).

O operador confirmou que a conferencia via Read-Host/pipe conectou ao banco e
retornou tres tabelas vazias e os cinco grupos de permissoes verdadeiros. A causa
exata da diferenca de entrada do getpass nao foi determinada; nao atribuir ao `$`
nem a uma vulnerabilidade do driver sem evidencia.

A entrada `--password-stdin` foi estendida para `--apply`. A carga ainda exige
hash revisado, computador Rigel, identidade SQL esperada, tabelas vazias,
transacao unica e conferencia de contagens. Para confirmar a nova versao no
servidor, a ajuda deve dizer `Com --check-database ou --apply` na opcao
`--password-stdin`. Nenhuma gravacao foi confirmada por essa mudanca de codigo.

## Carga confirmada e preparacao da credencial de runtime

O operador confirmou `carga_inicial_confirmada` para o snapshot revisado e
validou pela conta `sentinel_api` as contagens 49 regionais, 49 firewalls e 49
licencas. A carga inicial nao deve ser repetida. O banco ainda nao recebe
atualizacoes periodicas, e o site continua lendo seus arquivos/cache originais.

Os processos Python encontrados no Rigel executam sob `GALAXIA\admin.pimentel`.
Os executaveis incluem `services\alertad_v1\.venv`, Python311, `.venv31410` e
Python314. Isso confirma a identidade encontrada, nao identifica sozinho o
componente e o ambiente de cada PID. Nao instalar dependencias no runtime web
sem identificar o processo correto.

`scripts/database/configure_collector_secret.py` prepara somente a referencia
`sentinel/postgresql/collector/password` no cofre existente
`.credentials/sentinel-secrets.json`, usando `JsonSecretStore` e o protetor
DPAPI CurrentUser ja implementados no projeto. Nao usa DPAPI LocalMachine.

- Executar no Rigel como `GALAXIA\admin.pimentel`, nunca como `svc_pg_sentinel`.
- Transferir o novo script para `C:\Automacao\scripts\database`.
- Usar o ambiente de migracao e senha em JSON UTF-8 pelo pipe PowerShell.
- Valida primeiro uma conexao SQL somente leitura com destino e conta fixos.
- Recusa uma referencia que ja exista, sem substituir outras entradas.
- Grava somente a nova referencia e confere a leitura DPAPI de retorno.
- Nao altera coletores, consultas, frequencias ou senhas SQL; nao habilita sync.

Executar uma vez por preparacao, sem provisionadores concorrentes. Rotacao ou
mudanca de conta Windows deve ser planejada separadamente, nao por sobrescrita
automatica. O script verifica o destino SQL antes de armazenar a senha; uma
falha de conexao nao modifica o cofre. Falha posterior a gravacao exige conferir
a referencia antes de repetir. Testes locais usam conexao/cofre simulados;
o teste real do DPAPI ocorre somente quando o operador executar no Rigel.

## Runtime web identificado

O operador identificou a porta 5000 no Python314, iniciado pelo launcher
`C:\Automacao\.venv31410\Scripts\python.exe`. A porta 8000 pertence ao Aegis
em `C:\Aegis\.venv` e nao faz parte desta integracao.

Uma consulta no proprio `.venv31410` confirmou `tzdata` disponivel, Psycopg
ausente e leitura da referencia DPAPI do coletor bem-sucedida. A versao
`psycopg==3.3.9` / `psycopg-binary==3.3.9` foi registrada no requirements do
Sentinel, alinhada ao ambiente de migracao usado na carga inicial. Isso nao
instala os pacotes no Rigel automaticamente.

Instalar somente os dois pacotes nesse ambiente, sem atualizar as outras
dependencias ou instalar o requirements inteiro:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' -m pip install --no-deps --only-binary=:all: 'psycopg==3.3.9' 'psycopg-binary==3.3.9'
```

O teste seguinte deve usar o segredo DPAPI e `validate_connection` do script
de preparacao. Essa funcao abre transacao somente leitura e verifica usuario,
banco e porta, sem armazenar novamente a credencial. A instalacao do driver
e a conferencia nao habilitam sincronizacao, alteram coletores ou trocam as
leituras das telas. Nao reiniciar o servico nesta etapa.

O operador confirmou a instalacao dos dois pacotes no `.venv31410` e o teste
`Conexao PostgreSQL via DPAPI: OK`, com Psycopg 3.3.9. Nao repetir o cadastro
da credencial; o banco ainda contem somente a carga inicial.

## Conferencia dos arquivos antes da integracao

Hashes SHA-256 fornecidos pelo operador para o Rigel:

- `web_config.py`: `7B3C9DE8811FC4AEAFCED94A0F52C25A842C28D443A4E5B2512C350784BAD2A3`,
  igual a copia local antes de qualquer alteracao de integracao.
- `gerenciador_atualizacoes.py`: `9625023F64B7ED6C65A59F5807967F51DF5CD36C3C4719CD4B894FFC7DEF151A`,
  diferente da copia local (`CE4514628EED11C8845814D2AE9D7941B3B0EF28F046124152E93BDB79177A9F`).

Preservar o gerenciador do Rigel. Nao distribuir a copia local desse arquivo.
O ponto identificado para a futura integracao e `_salvar_cache_dashboard` em
`web_config.py`; o snapshot de firewalls e salvo antes do filtro de usuario.
Isso nao autoriza mudar as leituras das telas ou remover filtros AD.

Antes de migracoes adicionais ou ativacao, fazer novo dump do banco carregado.
O dump `sentinel-antes-importacao-20261112-164101-114.dump` foi feito antes da
carga e nao contem os 49 registros importados em cada tabela. Validar leitura
do catalogo nao substitui testar restauracao. A gravacao paralela ainda nao foi
implementada nem ativada no Rigel.

O operador criou depois o dump com dados
`E:\Sentinel\PostgreSQL\backups\sentinel-antes-sync-20261113-082123-975.dump`
(13.388 bytes), com leitura de catalogo bem-sucedida. O codigo local da gravacao
paralela e a migracao adicional foram preparados, ainda sem deploy/ativacao.
Procedimento detalhado: `docs/SENTINEL_POSTGRESQL_SINCRONIZACAO.md`.
