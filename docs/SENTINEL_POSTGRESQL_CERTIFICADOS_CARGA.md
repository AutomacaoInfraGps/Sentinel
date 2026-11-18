# Carga inicial de metadados legados de certificados

## Decisao de escopo

Auditoria Rigel em 18/11/2026: 3 certificados, 3 thumbprints distintos,
vencimentos ISO com fuso e nenhum registro invalido ou alias conflitante.
Um assunto e repetido, mas os thumbprints sao diferentes: nao fundir.
Na hora da auditoria, 1 tinha pelo menos 30 dias de validade e 2 estavam
expirados; os tres devem ser preservados. Essa classificacao muda com o tempo.

Usuario nao confirmou host/repositorio. Carga aprovada como metadados legados,
sem host, repositorio, regional ou evidencia temporal da coleta. Nao inferir
Acrab a partir do nome do arquivo, do alvo do coletor ou do assunto. Nao
usar mtime, importado_em ou data de simulacao como horario de coleta.

## Modelo 021

operacional.fontes_certificados_legados armazena a fonte logica
sentinel_certificados_relatorio_legado, hash dos bytes, digest da carga,
origem_confirmada=false e host_origem/repositorio_origem/codigo_regional/
coletado_em NULL. CHECKs impedem preencher ou confirmar esses vinculos nesta
etapa; novas evidencias exigem modelo e migracao separados.

operacional.certificados_legados armazena ordem na fonte, thumbprint textual
e normalizado, assunto, emissor, vencimento textual e vencimento_declarado
em timestamptz. Identidade limitada a fonte+thumbprint normalizado, nunca uma
instalacao global ou endpoint. Nao relacionar este legado a certificados
futuros com host confirmado sem conferencia de origem.

Aceita somente os quatro campos auditados e seus aliases TitleCase. Campos
extras, inclusive host/coleta/chaves/credenciais, bloqueiam para revisao em
vez de serem silenciosamente descartados. Rejeita aliases conflitantes,
duplicidades de thumbprint, metadados ausentes/nao textuais, dados invalidos,
datas sem fuso, datas localizadas e /Date(...)/ nao convertidas. Nao ha
opcao para assumir fuso ou consultar o coletor nesta carga.

Thumbprints hexadecimais de 40 ou 64 caracteres sao normalizados removendo
espacos e convertendo caixa para identidade; isso nao e verificacao
criptografica nem prova de validade do certificado. Campos textuais tem
espacos externos removidos; os bytes originais ficam vinculados pelo hash
e pela copia congelada. O vencimento original com offset e preservado em
texto junto ao instante UTC. Nenhum certificado expirado e descartado.

Nao persistir status valido/expirado nem dias restantes. O resumo calcula
validade apenas temporal em validade_avaliada_em_utc. Esse horario/status
nao entra no digest; o digest vincula fonte, bytes, projecao e desconhecimento
explicito da origem. Portanto repetir simulacao depois pode mudar o status
sem mudar o digest. Validade nao comprova uso, confianca, revogacao ou chave.

## Permissoes

Papel NOLOGIN sentinel_certificados_reader recebe SELECT, sem concessao
automatica a sentinel_api/sentinel_reader. Assuntos e emissores podem revelar
identidades internas. O collector recebe SELECT/INSERT, sem UPDATE/DELETE.
Nao alterar a conexao de leitura geral do DBeaver para contornar 42501.
Conferencias administrativas usam sentinel_admin. Importador nao imprime
assuntos, emissores, thumbprints, nomes de host, caminhos ou valores secretos.

## Fluxo de producao

021 esta preparada, nao aplicada/homologada pelo agente. Nenhuma alteracao
de tela, servico, coletor, fonte de dados ou sincronizacao automatica.

1. Publicar arquivos novos e fazer pull no Rigel.
2. Simular sem SQL:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\import_certificate_catalog.py'
```

3. Fazer novo pg_dump antes de 021.
4. Criar pasta nova restrita sob E:\Sentinel\PostgreSQL\backups e copiar
certificate_disk_report_acrab.json. Restringir ACLs a operador, SYSTEM e
Administradores. Nao publicar o JSON nem o backup no Git/chat.
5. Simular --source apontando a copia congelada; revisar contagens e digest.
6. Aplicar sql/021_certificate_legacy_catalog.sql por psql sentinel_admin,
porta 5433, banco sentinel, -X -v ON_ERROR_STOP=1. A migracao valida tambem
o data_directory E:/Sentinel/PostgreSQL/data; nao executar em outra instancia.
7. Conferir a copia com --check-database. Exigir duas tabelas vazias.
8. Aplicar com --source da copia --apply --expected-digest revisado.
9. Conferir contagens e origem desconhecida, sem repetir o --apply.

Default e simulacao sem conexao SQL, WinRM ou cofre. SQL exige RIGEL e source
explicito. Fonte e relida antes da conexao para detectar escrita concorrente.
A carga usa transacao, lock consultivo exclusivo, tabelas vazias, SQL
parametrizado e readback integral tipado da origem e dos certificados antes
do commit. Sucesso somente depois de confirmar o commit; erro nao deve
imprimir dados da fonte ou mensagem bruta do driver. Testes unitarios/mock
nao substituem conferencia de PostgreSQL real no Rigel.

## Conferencia administrativa

```sql
SELECT (SELECT count(*) FROM operacional.fontes_certificados_legados) AS fontes,
       count(*) AS certificados, count(DISTINCT thumbprint_normalizado) AS thumbprints
FROM operacional.certificados_legados;
SELECT origem_confirmada, host_origem IS NULL AS sem_host,
       repositorio_origem IS NULL AS sem_repositorio,
       codigo_regional IS NULL AS sem_regional, coletado_em IS NULL AS sem_coleta
FROM operacional.fontes_certificados_legados;
SELECT CASE WHEN vencimento_declarado < CURRENT_TIMESTAMP THEN 'expirado'
            WHEN vencimento_declarado < CURRENT_TIMESTAMP + interval '30 days'
              THEN 'a_vencer_menos_30_dias'
            ELSE 'valido_30_dias_ou_mais' END AS validade_temporal,
       count(*) AS certificados
FROM operacional.certificados_legados GROUP BY 1 ORDER BY 1;
```

Coleta nova com comprovacao do host/repositorio e evidencia de sucesso e
etapa propria. Nao ativar polling do arquivo legado como se confirmasse uma
consulta recente nem alterar leitores web enquanto essa origem e incerta.
