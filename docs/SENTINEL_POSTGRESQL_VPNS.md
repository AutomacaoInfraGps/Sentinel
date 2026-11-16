# VPNs: auditoria antes da modelagem

Firewalls/licencas, servidores e switches ja tiveram persistencia paralela
validada pelo operador. A etapa VPN comecou por auditoria sem SQL ou flag.

## Lacunas encontradas na auditoria inicial

- GerenciadorFortigate.obter_vpn_ipsec usa o resumo SSH do hub. Cada registro
  contem tunel, comentario, interface, status e ultima_verificacao HH:MM:SS.
- O fallback FortiManager informa device no envelope, mas nao nos registros.
- _prepare_vpn_operational_records preserva essa hora sem data, acrescenta nome,
  regional e status. Nao acrescenta dispositivo ou VDOM.
- publish_group_records e publish_map_snapshot compartilham o estado operacional.
  A publicacao do grupo nao comprova a data da observacao individual, nem uma
  consulta nova ao equipamento. O mapa e uma consolidacao derivada.

Nao usar regional como identidade do firewall: o tunel observado pertence ao
hub e a regional pode ser o destino remoto. Nao supor VDOM root nem reconstruir
observacao como "hoje + HH:MM:SS". Nao fundir tuneis so pelo nome.

## Conferencia no Rigel

Depois de commit/push e pull, executar no usuario operacional habitual:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    C:\Automacao\scripts\database\audit_vpn_sources.py
```

O comando le os JSONs locais existentes e o catalogo de regionais. Nao importa
configuracao de credenciais, nao acessa DPAPI, rede, Flask ou PostgreSQL e nao
grava arquivos. Exporta somente contagens e classificacoes fixas. Nao exporta
nomes, IPs, comentarios, codigos regionais, tokens ou valores de erros.

Ausencia de dispositivo/VDOM em um registro nao prova falta de configuracao do
coletor. A cobertura precisa ser corrigida na origem, com metadados verificados,
antes da carga inicial. Contagens de vinculo exato sao diagnostico de dados,
nao uma decisao de autorizacao de usuarios.

## Preparacao do coletor implementada, pendente de homologacao no Rigel

Nao altera tabela, agendamento, consultas existentes de VPN, filtros AD ou telas.
No SSH, acrescenta uma consulta somente leitura `get system status`, na mesma
sessao, com timeout de 10 segundos. Projeta somente Serial-Number, Hostname e
Current virtual domain. Valores ausentes, ambiguos, invalidos ou contexto global
nao recebem identidade ficticia. Falha dessa consulta nao impede a coleta de
VPNs; o SSH e fechado tambem quando ocorre falha.

Homologacao inicial: operador confirmou 166 registros SSH com serial e coleta
UTC, mas sem hostname/VDOM no JSON. O terminal manual informou hostname e VDOM
root explicitos. Parser agora aceita LF, CRLF, CR e sequencias ANSI CSI, mantendo
recusa de campos conflitantes/global. Isso corrige uma limitacao de formato;
nao prova que a resposta SSH automatica tinha CR/ANSI. Validar nova coleta real.
O valor root confirmado manualmente nao foi fixado no caminho SSH nem aplicado
retroativamente aos registros antigos.

Segunda homologacao confirmou hostname nos 166 registros mas ainda sem VDOM.
Antes de outras alteracoes, executar `scripts/database/check_vpn_ssh_context.py`
no Rigel, mesma conta Windows do coletor. O diagnostico resolve somente os tres
campos de conexao selecionados via mecanismo DPAPI existente, consulta uma vez
`get system status` sem PTY e classifica o VDOM retornado. Nao consulta VPNs,
nao grava SQL/cache, nao exporta resposta bruta, hostname, serial ou credenciais.
Usa known_hosts existente com RejectPolicy: chave desconhecida/divergente causa
falha, sem aceitacao automatica. Confirmar chave por canal confiavel, nao reduzir
essa verificacao. VDOM global e campo ausente sao resultados distintos.

Diagnostico real confirmou ausencia da linha de VDOM na resposta nao interativa,
apesar de serial/hostname presentes. Ainda nao esta comprovada a causa.
Opcao `--filtered-vdom` executa SOMENTE
`get system status | grep domain` na mesma conexao configurada.
Serve para testar resposta reduzida sem modificar console/paginacao/VDOM do
equipamento. O diagnostico inclui tamanho e deteccao de marcador --More--,
sem exportar a resposta bruta. Validar antes de mudar novamente o coletor.
O filtro sem aspas foi confirmado pelo operador na sessao interativa: root e
configuracao disable. A primeira variante filtrada automatica nao trouxe VDOM
(74 bytes), mas seu conteudo nao foi exportado e o motivo ainda nao foi provado.
O diagnostico agora tambem classifica mensagens de erro CLI e Return code
numerico sem exportar texto livre. Nenhum VDOM e preenchido por essa classificacao.
Referencia do filtro CLI: https://docs.fortinet.com/document/fortigate/7.0.8/administration-guide/416169/vm-license

## Resolucao do modo sem VDOMs, apos diagnostico real

O filtro automatico confirmou `Virtual domain configuration: disable`, sem
linha Current virtual domain e sem erro CLI detectado. O operador confirmou
root no terminal do mesmo hub. Isso permite uma regra de resolucao documentada,
nao um valor padrao para qualquer resposta incompleta:

- Priorizar Current virtual domain valido e nao conflitante.
- Se esse campo estiver totalmente AUSENTE, houver serial identificado e a
  configuracao for exclusivamente disable, resolver root com
  `vdom_origem=vdom_desabilitado`.
- Campo vazio, global, invalido/conflitante, modo multiple/ausente ou modos
  conflitantes nao autorizam essa resolucao.
- Se necessario, consultar uma vez `get system status | grep domain`, somente
  leitura na mesma sessao, unindo os campos antes de verificar conflitos.
- Falha dessa consulta opcional preserva a coleta e os metadados ja obtidos.
- Resposta explicita usa origem resposta_equipamento; fallback FM usa
  consulta_fortimanager. Auditoria mostra por_origem_vdom.

Referencia Fortinet para root em modo desabilitado:
https://docs.fortinet.com/document/fortigate/7.4.0/sd-wan-new-features/449965/fortiswitch-devices-can-be-imported-from-a-csv-file-fmg-7-4-2

Nao altera configuracao do FortiGate, nao exige PTY e nao altera dados antigos.
Pendencia: homologar novamente os 166 registros antes da modelagem SQL.

## Carga inicial preparada, ainda nao aplicada no Rigel

Operador confirmou 166 registros completos no estado operacional: 153 online,
13 offline, serial/hostname/VDOM/coleta com fuso em todos, origem do VDOM
vdom_desabilitado e nenhuma identidade composta repetida. A publicacao do mapa
mostrada na mesma auditoria ainda nao tinha VDOM. Nao importar do mapa.

Arquivos preparados:

- `scripts/database/sql/006_vpn_catalog.sql`: tabela operacional.vpns, owner
  sentinel_owner, leitor SELECT, coletor SELECT/INSERT, sem UPDATE/DELETE.
- `scripts/database/import_vpn_catalog.py`: simulacao por padrao; operacao SQL
  somente no Rigel, via conexao DPAPI existente; --apply exige --expected-digest.

A identidade e (firewall_serial, vdom, tunel), exata, sem casefold ou aproximacao.
O serial e do HUB consultado. Nao cria FK para o firewall da regional remota.
codigo_regional so recebe correspondencia exata ao catalogo. SEM_REGIONAL ou
codigo nao encontrado fica NULL com estado explicito, sem acesso global.

Esta primeira carga aceita APENAS fortigate_ssh com serial e VDOM completos.
Fallback FortiManager sem serial e bloqueado em vez de fundido por nome.
Modelar a correlacao verificada do fallback antes de habilitar escrita automatica.
Isso nao altera nem desliga o fallback das telas atuais.

O importador usa somente groups.vpns.records do estado operacional e o catalogo
regional. Aceita grupo publicado por vpn_manual ou mapa somente se TODOS os
registros tiverem metadados SSH completos. Snapshot derivado incompleto bloqueia
toda a carga. Nenhum item incompleto e descartado silenciosamente.

coletado_em exige ISO com fuso e e convertido para UTC. A hora legada fica em
coluna separada, sem inferir data a partir da publicacao do mapa ou do relogio.
Interface N/A vira NULL. Comentarios, campos arbitrarios e credenciais nao sao
armazenados no SQL nem impressos. Hashes dos dois arquivos brutos e projecao
tipada compoem digest_carga; nao publicar nem commitar os JSONs reais.

Procedimento incremental de implantacao:

1. Commit/push e pull dos arquivos preparados. Nao reiniciar: ainda nao ha hook.
2. Rodar apenas a simulacao:

```powershell
& 'C:\Automacao\.venv31410\Scripts\python.exe' `
    C:\Automacao\scripts\database\import_vpn_catalog.py
```

3. Rever contagens, origens e digest. Se a fonte viva for sobrescrita por um
   publicador antigo e perder VDOM, corrigir/recarregar esse publicador pelo
   procedimento habitual; nao preencher o JSON manualmente.
4. Novo backup custom do banco e verificacao pg_restore --list antes de 006.
   Isso nao equivale a teste real de restauracao.
5. Congelar copias PROTEGIDAS de sentinel_operational_state.json e
   estrutura_regionais.json no E:, fora do Git, com ACL de administracao/operador.
   O estado completo pode conter outros grupos e dados pessoais; nao compartilhar.
6. Simular novamente usando --source e --regionals nas copias congeladas.
7. Aplicar SOMENTE 006 como sentinel_admin, com psql -X/ON_ERROR_STOP=1.
8. Usar os mesmos dois arquivos com --check-database. Confirmar tabela vazia e
   todos os codigos do catalogo ja existentes no banco.
9. Usar --apply --expected-digest com o digest da copia congelada revisada.
   Uma transacao verifica identidade SQL, bloqueia regionais antes de vpns,
   exige tabela vazia, insere todos e valida contagens antes do commit.
10. Conferir contagens por status/vinculo como sentinel_api. Nao repetir bootstrap.

Sem sincronizacao automatica de VPNs nesta etapa, sem mudanca de leitores,
agendamentos ou AD, sem integracao SQL nova na SofIA. Leitor tecnico nao e
autorizacao de usuario: futuras consultas precisam aplicar escopo AD no backend.
As permissoes desta migracao nao incluem UPDATE porque o lock da tabela filha
e ROW EXCLUSIVE; exclusao entre cargas e coordenada pelo lock de regionais.
Testes locais usam cursores simulados; a migracao ainda exige homologacao PG real.

No FortiManager, preserva o VDOM root ja utilizado pelas duas chamadas existentes
e acrescenta device efetivamente selecionado. Nao afirma que root e o contexto
da sessao SSH e nao inventa serial para o equipamento consultado via proxy.

Cada registro novo recebe `vpn_source`, `device_namespace` e `coletado_em` ISO
com UTC. Dispositivo/serial/VDOM sao incluidos quando conhecidos. O namespace
separa endpoint SSH de instancia FortiManager/ADOM; nao e identidade definitiva
para unificar as fontes. Troca de membro HA, renomeacao e correlacao por serial
precisam ser consideradas na futura modelagem, nao fundidas pelo nome do tunel.

`coletado_em` representa o instante local de recebimento do resultado da consulta,
nao o horario fornecido pelo equipamento nem o inicio de uma indisponibilidade.
O campo legado ultima_verificacao continua HH:MM:SS para preservar a tela.
A auditoria mostra `horarios_coleta` e `por_fonte_coleta` separadamente.
O horario de publicacao do grupo pode continuar sem fuso e nao substitui coleta.

Referencia do formato dos campos de contexto:
https://docs.fortinet.com/document/fortigate/7.6.1/administration-guide/576344/adding-vdoms-with-fortigate-v-series

Depois de commit/push e pull no Rigel:

1. Reiniciar pelo `restart_web_service.ps1` e confirmar healthz HTTP 200.
2. Executar uma atualizacao real de VPN na tela existente e aguardar conclusao.
   Abrir uma tela com cache fresco nao garante nova consulta.
3. Rodar novamente `audit_vpn_sources.py`. Esperar `horarios_coleta.com_fuso`
   nos registros novos. Conferir dispositivo/VDOM e fonte efetivamente usada.
4. A consolidacao do mapa pode ocorrer depois; os dois arquivos nao precisam
   ser instantaneamente iguais. Registros antigos nao sao preenchidos retroativamente.

Os testes de transporte simulado executam os metodos de producao isolados por
AST, sem importar credenciais reais: contexto SSH, falha opcional de contexto,
fechamento na falha, VDOM do fallback e preservacao no preparo operacional.
Nao houve consulta aos equipamentos ou gravacao no banco no ambiente local.

## Proximas etapas, ainda nao executadas

1. Conferir a auditoria real, inclusive duplicidades e horarios.
2. Homologar os metadados novos em coleta real, distinguindo SSH e fallback.
3. Validar nova publicacao sem mudar agendamento, filtros AD ou leitores atuais.
4. Preparar tabela e importador tipado, backup, simulacao e carga congelada.
5. Habilitar persistencia paralela somente apos homologacao manual.

Dados antigos sem identidade ou data suficiente nao ganham valores ficticios.
Nao ha conexao nova com a SofIA nesta etapa. Leituras futuras continuam exigindo
escopo autorizado no backend; VPN sem regional nao concede acesso global.
