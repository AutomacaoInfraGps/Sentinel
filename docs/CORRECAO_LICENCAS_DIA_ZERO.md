# Licenca com zero dias deve permanecer critica

## Defeito

O operador informou FortiCare da Nutricar com vencimento conhecido e zero dias,
mas linha verde na aba de firewalls e sem alerta de licenca no mapa. A regra
0 < dias_restantes <= 60 excluia precisamente o dia zero. O contador de licencas
e o mapa dependiam desses flags, de modo que o alerta desaparecia nessa fronteira.

## Regra aplicada

services/firewall_licenses.py centraliza flags usados pelo normalizador,
contadores, sinalizacao das regionais e recalculo do mapa (inclusive cache):

- Zero dias com vencimento conhecido e informacao disponivel: vencimento_critico,
  alerta_vencimento e notificacao_critica verdadeiros. Nao declara que o instante
  de expiracao ja passou somente porque o numero de dias e zero.
- Positivos ate 60 dias: preserva alerta a vencer existente, inclusive se a
  origem informou dias positivos sem timestamp. Acima de 60 nao alerta. A nova
  exigencia de vencimento real impede promover zeros sintetizados a critico.
- Negativos com vencimento conhecido, status expired/no_license ou flag de
  expiracao valido: expirado/critico, sem rebaixar a verde.
- Data ausente/invalida e dias None/bool/NaN nao viram dia zero critico.
- Licenca indisponivel/offline/unknown suprime flags antigos de vencimento.
- Esta mudanca nao recalcula dias observados ou interpreta horario SQL como
  data nova de coleta. Nao altera o limiar de 60 dias nem os agendamentos.

Na aba, badge da licenca fica vermelho no dia zero, com 0 dias, e o card recebe
badge separado de licenca critica. O badge Online continua representando a
disponibilidade do equipamento. Dado sem prazo aparece nao informado, nao 0 dias.

No mapa, firewall acessivel com licenca critica continua disponibilidade online,
mas produz alerta de severidade critico (vermelho), mantendo a descricao
licencas a vencer para o resumo existente mostrar Licenca vence hoje.
Nao duplica o mesmo firewall nos totais de alerta critico e warning.
Offline/inativo/manutencao nao passam a gerar alerta adicional de licenca;
manutencao regional continua preservando a severidade de manutencao.
Um vencimento nunca e convertido em firewall offline.

## Verificacao e implantacao

Testes isolados executam as funcoes reais de contadores/mapa/normalizador por
AST, sem importar o Flask completo ou acessar credenciais. Incluem fronteiras
zero/1/30/60/61, prazo ausente, indisponibilidade, manutencao, mistura de
firewalls e renderizacao Jinja da linha de licenca. Testes JavaScript existentes
conferem resumo vence hoje e comportamento de dados parciais.

Depois de commit/push e pull no Rigel, reiniciar pelo restart_web_service.ps1,
conferir healthz e abrir firewalls/mapa. Recalculo corrige flags nas leituras
normais do cache, sem apagar arquivos. A publicacao SQL desses novos flags ocorre
na proxima coleta/publicacao normal de firewalls; a correcao nao grava snapshots
artificialmente nem altera timestamps antigos. Conferir tambem pela atualizacao
existente da aba de firewalls quando for necessario validar o coletor completo.

Nao ha migracao SQL nova nesta correcao. Migracao 004 e carga de switches ainda
aguardam homologacao do erro de contexto do botao informado anteriormente.
Nao executar ambas as atividades como se ja estivessem confirmadas.
