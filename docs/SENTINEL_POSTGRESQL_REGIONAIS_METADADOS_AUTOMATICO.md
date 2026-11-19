# Espelhamento automatico dos metadados regionais

## Estado de partida confirmado

025/026 aplicadas no Rigel. Nova captura manual conferida com 51 metadados
preservados/presentes, nenhum codigo/nome divergente, descricao e estado/UF
concordantes. Marcador: 2026-11-19T10:24:43.196292-03:00. Digest revisado:
7e9f4b1bc3abcdf724ba9fac809a3a655518be08f81f2a4bc520a3acead43fc2.
sha256_metadados: aed53b775b365216945d7fa8ec83d018ac81756afbce97cd0d323056e0342b61.
Worker ativado no Rigel e recorrencia confirmada pelos resultados enviados pelo
operador em 19/11/2026. Primeiro commit automatico: 11:09:39.532106 -03:00;
commit posterior: 14:49:55.985518 -03:00, captura 14:49:55.470375 -03:00.
Ambos com modo sincronizado, 51 regionais e flag automatico true.

Conferencia --current as 14:50:20 -03:00: 51 preservadas/presentes,
conteudo_atual_confere=true, zero codigos ausentes, nomes divergentes ou
regionais fora do cadastro, sem conflitos/regressoes. sha256_metadados permanece
aed53b775b365216945d7fa8ec83d018ac81756afbce97cd0d323056e0342b61.
conteudo_ja_sincronizado=false nessa leitura nao indica divergencia: a conferencia
criou outra captura, posterior ao marcador, sem gravar. Estes resultados comprovam
os ciclos observados, nao monitoramento continuo nem conexao remota desta revisao.

## Escopo e controles

services/operational_regional_metadata.py inicia pelo run_web_service.py,
independente de abrir uma tela. Thread daemon unica por processo, file lock
entre processos e advisory lock SQL da carga/sync manual. Um ciclo na
inicializacao e depois a cada 300 segundos contados apos o ciclo anterior.
Nao cria agendamento no Windows ou jobs de equipamentos. Nao exige SQL novo.

Somente no Rigel e com enabled exatamente true em
instance/operational-postgres-regional-metadata-shadow.json. Flag ausente,
false, invalido ou fora do Rigel: sem leitura da fonte ou conexao SQL. Nenhum
arquivo habilitado e criado automaticamente. Fonte fixa:
estrutura_regionais.json em PROJECT_ROOT, sem caminhos secretos/configuraveis.

Usa capture_payload/build_catalog da etapa 025, lendo a fonte duas vezes para
detectar alteracao durante a leitura. Somente codigo/nome/descricao/estado/uf
entram na projecao em memoria. Nao salva cadastro original, dispositivos ou
credenciais. Nao importa gerenciador de regionais/servidores, SLA ou web_config.
A conexao SQL usa o collector ja configurado, nao credenciais dos equipamentos.

O escritor 026 preserva a carga inicial, bloqueia regressao/conflitos de captura
e publicacao, fuso incompativel e codigos/nomes divergentes do cadastro principal.
Nao escolhe UF nem resolve aliases. Fonte vazia/invalida, descricao em branco,
UF conflitante ou campos fora dos limites bloqueiam o ciclo, sem limpar SQL.
Se o cadastro principal ainda nao refletir uma edicao legitima, sincronizacao
de metadados aguarda, sem mudar a identidade para contornar o erro.

Nomes/codigos/presenca de operacional.regionais, vinculos de equipamentos,
pessoas/contatos e planilha SLA permanecem inalterados. Nao altera escritores
existentes, leitores das telas ou a configuracao dos demais espelhamentos.
Ausentes continuam preservados e marcados, sem DELETE. Dados iguais atualizam
apenas marcador; descricao/UF nao sao regravados nesse caso.

Flag e reconferido antes da conexao/escrita e antes de confirmar transacao;
desabilitacao nesse ponto causa rollback. Excecoes usam aviso seguro sem valores
brutos. Falha nao derruba o web; nova tentativa ocorre no proximo intervalo.
Publicacao legada sem fuso nao recebe zona inferida; comparacao continua no eixo
textual declarado, conforme 026. Captura/sincronizacao nao sao edicao ou coleta.

## Conferir antes de habilitar

Publicar codigo e fazer pull no Rigel. Manter flag ausente/false inicialmente.

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    'C:\Automacao\scripts\database\sync_regional_metadata_catalog.py' `
    --current
```

--current le cadastro atual e compara com SQL readonly; nao executa o worker ou
aceita --apply. Gravacao manual continua exigindo --source congelado e digest
revisado. Esperado conteudo_atual_confere=true, 51 presentes e zero divergencias.
conteudo_ja_sincronizado pode ser false porque horario/hash da nova exportacao
diferem do marcador. O primeiro campo verifica os dados tipados; o segundo
exige tambem recibo/marcador exatamente iguais.

sincronizacao_automatica_metadados em --current informa o flag, nao prova de
processo ativo, reinicio ou ciclo concluido. Recorrencia precisa de status
pos-commit e marcador avancando em ciclos distintos.

## Ativacao controlada

Apos revisar a conferencia, no Rigel sob a mesma conta operacional:

```powershell
if ($env:COMPUTERNAME -ne 'RIGEL') { throw 'Execute somente no Rigel.' }
Set-Content `
    -LiteralPath 'C:\Automacao\instance\operational-postgres-regional-metadata-shadow.json' `
    -Value '{"enabled":true}' -Encoding utf8

powershell -ExecutionPolicy Bypass -File C:\Automacao\restart_web_service.ps1
```

Reiniciar so o servico web via script existente, sem mudar conta, credenciais,
portas ou tarefa. Nao reiniciar PostgreSQL. Conferir primeiro ciclo:

```powershell
Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz'

Get-Content 'C:\Automacao\output\regional_metadata_postgres_sync_status.json' -Raw |
    ConvertFrom-Json |
    Select-Object modo, regionais, sincronizacao_automatica_metadados,
        capturado_em, confirmado_em_utc |
    Format-List
```

Status e escrito atomicamente somente apos commit; contem apenas resumo com
hashes/contagens/formatos temporais, nunca codigos, nomes, descricoes, enderecos
ou credenciais. Nao e uma captura reaplicavel. Se falhar gravacao do status
depois do commit, banco pode estar atualizado: conferir antes de repetir apply.

Repetir depois de pelo menos 5 minutos contados de confirmado_em_utc, com
horario atual junto. Status antigo nao prova falha antes do intervalo nem saude
continua depois dele. Confirmar dois horarios avancando e --current com dados
iguais/zero conflitos, antes de declarar recorrencia homologada. Lembrar:
status em UTC, horario do Rigel confirmado como Brasilia (UTC-03:00).

Se nao avancar apos intervalo, nao reiniciar ou reaplicar carga imediatamente.
Conferir flag, horario, processo ativo e avisos do arquivo correto:

```powershell
Get-Content 'C:\Automacao\logs\web_task_stderr.log' -Tail 3000 |
    Select-String -SimpleMatch 'falha_sincronizacao_metadados_regionais'
```

## Desativar

```powershell
Set-Content `
    -LiteralPath 'C:\Automacao\instance\operational-postgres-regional-metadata-shadow.json' `
    -Value '{"enabled":false}' -Encoding utf8
```

Sem exclusao de tabelas/arquivos, reset de marcadores ou restart de PostgreSQL.
Commit ja concluido nao e desfeito. A leitura das telas permanece nas fontes
atuais. Esta entrega nao transforma o PostgreSQL na fonte de edicao principal.
