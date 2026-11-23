# Indisponibilidade informada pelo FortiManager

## Incidente ORMEC PARA (19/11/2026)

Print do FortiManager mostra FTG_ORMEC_PARA com indicador de desconexao.
SD-WAN com Status Enable e configuracao persistida, nao prova conectividade.
Isso nao comprova, por si so, o estado de todos os servidores/APs da unidade.
Nenhum teste de producao foi executado pelo agente para confirmar a causa da queda.

## Falhas encontradas

- Resolver usado pelos links reduzia o device a nome/IP, descartando conn_status.
- Funcoes de links/firewalls tinham interpretacoes numericas conflitantes;
  valores zero eram descartados pelo uso de or string vazia.
- Status de licenca e dev_status eram usados como fallback de disponibilidade,
  embora nao comprovem conexao ativa com o dispositivo.
- A coleta principal descartava o firewall quando a consulta de licenca lancava
  excecao, justamente quando o dispositivo podia estar indisponivel.
- Falha de interface preservava os links anteriores sem diferenciar um erro
  generico do proxy de uma desconexao explicita informada pelo inventario atual.

## Correcao

Listagem de devices solicita verbose=1 para receber enums textuais. A API HOW-TO
mostra esse formato e conn_status up na resposta:
https://how-to-fortimanager-api.readthedocs.io/en/latest/007_device_management/007_device_management.html

Somente up/down (ou equivalentes textuais explicitos) determinam conexao.
Valores numericos legados 0/1/2 nao sao adivinhados: disponibilidade desconhecida
ate nova consulta textual. Unknown nao deve virar inativo administrativo nem
online apenas porque existe licenca registrada. Manutencao explicita prevalece.

Resolver preserva apenas status/conn_status/dev_status, nome e IP no device
selecionado; nao copia senhas ou todos os campos brutos do inventario.
Inventario atual com desconexao explicita evita consultas de interfaces/licenca
ao FortiGate inacessivel. A identidade do firewall continua no resultado mesmo
com erro de licenca, que passa a ser uma informacao independente.

Para links ja conhecidos, uma desconexao explicita do inventario LIVE produz
status offline com modo_verificacao fortimanager_device_offline,
estado_inferido_do_firewall=true e disponibilidade_observada_em. Identidades/IPs
continuam os anteriores; nao se inventam novos links. Sem links conhecidos,
retorna pendencia, nao WAN ficticia. Cache antigo dizendo down ou simples falha
do proxy nao bastam para fabricar uma nova constatacao de queda.

Nao inventar packet loss 100%, SLA inativo ou timestamp de medicao individual.
coleta_status_confirmada=false; coletado_em anterior e preservado. O horario
de disponibilidade do firewall fica separado. Ao recuperar uma consulta real
de interface, a inferencia e removida e a evidencia individual volta a prevalecer.

## Banco e telas

Links derivados do firewall usam a mesma base canonica das telas, inclusive a
reconciliacao de links do mapa implementada na correcao SD-WAN anterior.
Atualizar a tela Firewalls tambem e necessario para renovar seu cache proprio;
mapa antigo pode precisar da atualizacao do snapshot para renovar a camada de
firewalls, nao apenas a de links. Nao reiniciar PostgreSQL.

O espelho SQL de links continua aceitando apenas medicoes confirmadas de
interface/SD-WAN. Esta mudanca NAO mascara a inferencia do firewall como medicao
individual para faze-la entrar no banco; persistencia SQL dessa evidencia de
disponibilidade separada fica pendente. Nao afirmar que os leitores foram
migrados ao PostgreSQL ou que todos os equipamentos da regional estao offline.

## Verificacao no Rigel

Publicar/pull, combinar reinicio web sem jobs/checklist ativos. Atualizar
Firewalls e Links e revisar resultado por regional. Conferir FTG_ORMEC_PARA:
conn_status textual, disponibilidade offline, identidade preservada mesmo sem
licenca acessivel; links conhecidos offline com inferencia explicita. Atualizar
mapa e comparar com a mesma regional. Se continuar ausente, coletar resultado
do job e dados sanitizados do vinculo, sem editar JSON, rede ou dados SQL.

Testes locais isolam app/cofre/rede. Cenario real no Rigel ainda nao homologado.
