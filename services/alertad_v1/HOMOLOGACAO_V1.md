# Homologação da v1

Execute somente no ambiente corporativo autorizado. Não compartilhe credenciais,
tokens, certificados privados, XML não anonimizado ou identificadores internos.

## Preparação

- [ ] Conta de serviço lê `ForwardedEvents` e grava apenas nos diretórios locais.
- [ ] Banco, logs, configuração e cache possuem ACL restrita.
- [ ] Dependências e suíte automatizada foram instaladas/executadas.
- [ ] Polling, sobreposição e decisão “histórico ou a partir de agora” foram aprovados.
- [ ] Banco de homologação é separado e inicializado com `--dry-run`.

## ForwardedEvents

- [ ] Eventos dos três DCs aparecem no canal local.
- [ ] Os seis IDs aparecem quando gerados por procedimento aprovado.
- [ ] XML preserva `Computer` de origem, canal, EventID, EventRecordID e timestamp.
- [ ] Uma leitura seguinte retoma o bookmark sem reler o canal completo.
- [ ] Reinício do processo retoma o mesmo checkpoint.
- [ ] Backlog é consumido em lotes de no máximo 500.
- [ ] Sobreposição pode reler itens, mas não cria novo evento/alerta.
- [ ] Permissão negada e bookmark inválido produzem erro sanitizado visível.

Não limpe o canal produtivo para testar rotação. Esse cenário já é automatizado com
fake; valide em canal/laboratório aprovado se a empresa exigir.

## Parser e regras

- [ ] Fornecer internamente seis XMLs anonimizados para comparação de campos.
- [ ] Grupo não monitorado não consulta o diretório.
- [ ] Cada grupo monitorado produz ação/mensagem correta.
- [ ] Evento malformado vira ocorrência e o evento seguinte é processado.
- [ ] Mesmo EventRecordID vindo de DCs diferentes permanece distinto.

## PowerShell/ADWS

- [ ] Módulo ActiveDirectory está instalado no Rigel.
- [ ] `Get-ADUser -Identity <SID>` funciona sob a identidade aprovada do worker.
- [ ] Conta de serviço somente leitura ou gMSA executa sem senha no AlertAD.
- [ ] Descoberta normal do domínio ou `directory.server` aprovado alcança o ADWS.
- [ ] SID de usuário retorna conta, domínio, display name e classe `user`.
- [ ] SID ausente, computador, timeout e indisponibilidade usam fallback SID.
- [ ] Nenhuma consulta altera o Active Directory.
- [ ] `simulate-missing-member` resolve um XML real com `MemberName` forçado
  apenas em memória, sem persistir a credencial temporária.

## Dry-run ponta a ponta

- [ ] Capturar `--initialize-at-end` somente uma vez.
- [ ] Gerar evento de homologação aprovado.
- [ ] Executar `--dry-run --once` sem `--initialize-at-end`.
- [ ] Confirmar mensagem local, evento no banco e avanço do checkpoint.
- [ ] Reexecutar e confirmar ausência de nova mensagem/duplicidade.
- [ ] Reiniciar e repetir com novo evento.
- [ ] Confirmar que o banco dry-run não contém entregas.

## Graph controlado

- [ ] Consentimento `Mail.Send`, remetente e destinatários de homologação aprovados.
- [ ] Consentimento delegado `ChatMessage.Send`, conta e chat existentes aprovados.
- [ ] Cache do Teams renovado e protegido.
- [ ] E-mail e Teams recebem o snapshot esperado.
- [ ] Falha controlada em Teams não impede e-mail, e vice-versa.
- [ ] Resposta 429/5xx agenda retry sem expor corpo/token.
- [ ] Operação aceita a possibilidade de duplicata após resultado `uncertain`.

## Operação

- [ ] Tarefa inicia sem sessão de usuário e recusa segunda instância.
- [ ] Reinício do Rigel recupera coleta e entregas pendentes.
- [ ] Parada controlada não deixa transação parcial.
- [ ] `status`/`diagnose` mostram geração abreviada e sequência lógica, sem
  bookmark bruto; falha de leitura em `--once` retorna código não zero.
- [ ] Logs giram e permanecem livres de segredos.
- [ ] Tempo evento → alerta foi medido e atende a meta aproximada de 30 segundos.
- [ ] Volume e espaço em disco foram observados.
- [ ] Janela real de replay foi medida para uma futura decisão de retenção;
  expurgo permanece desabilitado nesta v1.

## Evidências seguras

Registre somente: horário, código de retorno, contagens, razão sanitizada e
identificadores artificiais. Antes de compartilhar qualquer log, remova SID, UPN,
nomes, hosts, tenant, chat, request IDs e caminhos internos quando não forem
necessários ao diagnóstico.
