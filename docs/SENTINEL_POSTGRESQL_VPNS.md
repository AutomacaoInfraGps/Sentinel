# VPNs: auditoria antes da modelagem

Firewalls/licencas, servidores e switches ja tiveram persistencia paralela
validada pelo operador. A etapa VPN comeca SEM migracao SQL, importacao ou flag.

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
