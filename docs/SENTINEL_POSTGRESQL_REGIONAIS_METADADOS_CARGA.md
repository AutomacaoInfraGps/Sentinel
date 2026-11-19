# Carga inicial de metadados regionais

## Evidencia do Rigel

Auditoria recebida: 51 regionais com nome, descricao, estado e uf preenchidos;
51 siglas reconhecidas em ambos os campos, sem conflitos textuais ou normalizados,
sem duplicidades de codigo, espacos externos, nomes acima de 240 ou descricoes
acima de 500. Publicacao declarada do cadastro sem fuso. Hash do arquivo na
auditoria: 97ca0a7b740544a2050c253fbd8f85379661c363dbb58b293bfa71744e9fa38d.
O arquivo pode mudar por atualizacao de dispositivos, sem mudar os metadados.

Backup confirmado antes da etapa: E:\Sentinel\PostgreSQL\backups\
sentinel-antes-metadados-regionais-20261119-093400-707.dump, 194917 bytes,
19/11/2026 09:34:10. Nao confundir com a primeira tentativa, que falhou por
ausencia de senha. Essa tentativa falha nao e um backup valido.

## Modelo e limites

025 cria fontes_metadados_regionais e metadados_regionais no schema operacional.
Cada linha referencia o codigo existente em operacional.regionais, com FK
ON UPDATE CASCADE e ON DELETE RESTRICT. Guarda nome_origem para conferencia,
descricao e os dois campos estado/uf iguais, com siglas validadas. Nao altera
codigo/nome/presenca, servidores, aliases de sites/SLA, permissoes AD ou telas.
Essa projecao nao significa cobertura integral de todos os campos do cadastro.

A publicacao legada e guardada como texto sem conversao/inferencia de fuso.
capturado_em e horario UTC da exportacao, nao data de alteracao ou coleta de
equipamento. Hash da origem cobre os bytes do cadastro inteiro; sha256_metadados
cobre apenas a projecao ordenada dos cinco campos. Digest inclui captura,
publicacao e hashes. Hash nao e assinatura ou autorizacao.

Descricoes podem conter enderecos/contexto interno. Leitura fica no papel
dedicado sentinel_regionais_metadados_reader NOLOGIN, sem grant automatico
para sentinel_reader/sentinel_api. Collector recebe somente SELECT/INSERT nas
novas tabelas. Nenhuma credencial, lista de servidores/links ou outro campo
da regional e exportado/importado. Fonte original e lida duas vezes para
detectar alteracao; nunca e salva pelo importador.

## Etapas no servidor

Simular sem acessar banco ou cofre:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\import_regional_metadata_catalog.py'
```

O modo inicial exige os cinco campos preenchidos e siglas exatamente iguais
e validas. Vazios, UF conflitante, textos longos ou espacos externos bloqueiam;
nenhum campo e truncado, escolhido por alias ou inferido automaticamente.

Apos revisar, criar pasta NOVA e restrita em E:\Sentinel\PostgreSQL\backups,
com acesso apenas ao operador, SYSTEM e Administrators, como nas cargas
anteriores. Capturar sem copiar o cadastro completo com credenciais:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\import_regional_metadata_catalog.py' `
    --capture 'E:\Sentinel\PostgreSQL\backups\PASTA_DA_CARGA\metadados-regionais.json'
```

O arquivo contem nomes/descricoes/UF internos: nao versionar ou publicar.
Criacao exclusiva, sem sobrescrever arquivo. Em falha de escrita, nao reutilizar
eventual arquivo parcial. Conferir com --source antes de qualquer carga SQL.
O digest mudara pela nova captura, mesmo sem alteracao de metadados.

Somente depois de confirmar backup e captura, aplicar migracao:

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' `
    -X -h 127.0.0.1 -p 5433 `
    -U sentinel_admin -d sentinel -W `
    -v ON_ERROR_STOP=1 `
    --file='C:\Automacao\scripts\database\sql\025_regional_metadata_catalog.sql'
```

Conferir readonly com import_regional_metadata_catalog.py --source CAMINHO
--check-database. Esperado: zero regionais ausentes, nomes divergentes ou
regionais fora do cadastro atual; duas tabelas vazias, conteudo ainda nao
igual a captura. Se divergir, nao ajustar nomes/vinculos automaticamente.

Apos revisar, aplicar com --source CAMINHO --apply --expected-digest DIGEST
da captura congelada. Depois repetir --check-database: 1 fonte, 51 metadados,
conteudo_confere_com_captura=true. Conferencia administrativa com sentinel_admin:

```sql
SELECT (SELECT count(*) FROM operacional.fontes_metadados_regionais) AS fontes,
       count(*) AS regionais,
       count(*) FILTER (WHERE estado = uf) AS estado_uf_concordantes
FROM operacional.metadados_regionais;
```

## Controles da carga

SQL exige --source congelado, RIGEL, collector no sentinel/5433 e digest exato
na gravacao. A migracao valida banco/porta/data_directory. O writer usa advisory
lock, trava curta SHARE na tabela regionais para impedir mudanca durante a
conferencia/insercao e ROW EXCLUSIVE nas novas tabelas. Usa permissoes existentes
do collector no cadastro; nao concede privilegios gerais para contornar erros.

Bloqueia segunda carga e cadastro divergente. INSERT parametrizado e conferencia
tipada de origem e todas as linhas antes do commit; qualquer erro cancela a
transacao. Sucesso so e emitido apos o contexto de commit. Nao ha UPDATE/DELETE
de regionais ou metadados. Sem reinicio de PostgreSQL ou servico web nesta etapa.
Fonte congelada e a evidencia revisada, nao promessa de que o cadastro vivo nao
mudou depois; futuras sincronizacoes exigem etapa propria.

Codigo/migracao preparados e testados localmente. Captura congelada, migracao
025 e carga ainda nao confirmadas no Rigel. Automatizacao e leitor SQL das
telas nao foram alterados.
