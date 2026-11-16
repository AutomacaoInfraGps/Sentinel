# Vencimento de licencas no sino

## Comportamento

O sino passa a usar os mesmos limites de services/firewall_licenses.py para
licencas, mesmo quando o status antigo do firewall ainda estiver online sem
warning. Nao realiza coleta nova nem consulta SQL adicional.

- Zero dias com vencimento conhecido: titulo Licenca de firewall vence hoje,
  mensagem com produto/equipamento e 0 dias restantes, severidade critical.
- Expirada: titulo vencida, sem afirmar que ainda vai vencer hoje.
- Dias positivos ate 60: informa produto e quantidade de dias, severity important.
- Data desconhecida com zero nao e promovida a vencimento real.
- Offline/inativo/manutencao nao produzem notificacao adicional de licenca;
  alertas existentes de disponibilidade continuam independentes.
- Uma notificacao por firewall, priorizando sua licenca critica/mais proxima.
  Nao duplica o aviso generico warning quando ha um prazo concreto a apresentar.
- Warning sem detalhes de licencas preserva o comportamento generico anterior.

Ordem: licencas criticas, licencas a vencer (menor prazo primeiro), VPNs orfas,
baseline de administradores e demais eventos. Preserva a ordem relativa das
pendencias anteriores e a ordenacao temporal entre itens da mesma prioridade.
As classes critical/important e o renderer textContent ja existem no frontend;
nenhum HTML fornecido pela origem e inserido como markup.

ID inclui produto/faixa/dias para que uma notificacao vista/limpa anteriormente
nao esconda a escalada para zero dias, mesmo sem mudanca em changed_at. Leitura
e limpeza continuam por usuario, sem tornar alertas de licenca persistentes.

## Permissoes e atualidade

api_notifications continua autenticado e aplica filter_records com grupos do
usuario ANTES de build_notifications. Nao buscar outros firewalls/caches depois
desse filtro nem aceitar escopo regional vindo do navegador.
O teste isolado executa essa funcao real com filter_records real para o grupo
GGS_SUPORTE_NUTRICAR, excluindo outro firewall da TLSV_POA.

Atualidade e aviso de snapshot antigo seguem a API existente. Os dias continuam
observados, nao sao recalculados silenciosamente pelo sino. Dados antigos nao
recebem horario atual para aparentar uma nova coleta.

## Implantacao

Commit/push e pull no Rigel; reiniciar pelo restart_web_service.ps1 e conferir
healthz. Abrir o sino para validar titulo/mensagem, posicao e vermelho no
vencimento de zero dias. O polling existente recarrega o resultado.
Sem nova migracao SQL, alteracao de cofre, agendamento ou permissao AD.

Testes cobrem limites, desconhecidos, expiracao, manutencao, disponibilidade,
deduplicacao por firewall, IDs de escalada, leitura/limpeza por usuario e filtro
regional do endpoint. Visualizacao real no Rigel ainda precisa ser homologada.
