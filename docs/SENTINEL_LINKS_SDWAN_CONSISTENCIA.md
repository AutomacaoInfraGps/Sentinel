# Links SD-WAN e consistencia das telas

## Diagnostico em 19/11/2026

Print do Sentinel: REG_LEOPOLDO_B2 com WAN1/WAN2 offline, ultima verificacao
12/11. Prints do FortiManager: WAN1/WAN2 Down e sem IP; painel SD-WAN usa dmz
(VIVO) e ha1 (ALGAR), com IPs publicos e link mode conectado. As capturas nao
confirmam o estado administrativo dessas portas; Down nao comprova desabilitacao.
Tambem nao comprovam isoladamente sucesso de todo health-check.

Codigo apresentava filtros para excluir dmz/ha1 salvo alias contendo WAN.
A selecao ocorria antes da consulta aos membros SD-WAN. Com alias VIVO/ALGAR,
interfaces usadas pela unidade podiam ser descartadas e a coleta retornar
wan_not_found, preservando o cache antigo. O resultado real do job no Rigel
ainda deve ser conferido; nao atribuir o incidente a equipe de redes sem evidencias.

Na consulta rapida, interfaces reconstruidas do cache tambem nao recebiam portas
novas presentes somente no monitor runtime. O mapa podia servir seu proprio
snapshot antigo depois da atualizacao dos links na base compartilhada.

## Correcao preparada

- Resolver membros SD-WAN antes de filtrar as interfaces.
- Permitir dmz/ha1 com IP publico e participacao confirmada, sem exigir WAN no
  alias. Preservar os filtros contra tuneis, VPN, interfaces internas e IP privado.
- Persistir sdwan_member_confirmado junto ao registro normalizado para a mesma
  selecao funcionar ao ler links_internet_auto. Nao codificar excecao por regional.
- Incorporar portas novas da resposta runtime mesmo na coleta sem configuracao.
- Ao ler cache do mapa, reconciliar somente links com links_internet_auto e
  recalcular totais/alertas. Nao executar coletores adicionais nessa reconciliacao,
  gravar novo cache ou alterar o horario das medicoes de outros dispositivos.
- Infra, detalhes regionais e mapa passam pela mesma selecao canonica. Telas ja
  abertas precisam da proxima requisicao/atualizacao; nao ha push para o navegador.

Isso nao muda leitores para PostgreSQL. O banco ainda e espelho paralelo, como
documentado na cobertura da migracao; gravar nele sozinho nao unifica leitores.
Relatorios HTML/PDF previamente gerados continuam sendo documentos de sua geracao.
Nao regenerar checklist inteiro ou historico automaticamente nesta correcao.

## Sobre inativo e offline

Nao reclassificar Down, SLA inactive, ausencia de IP ou falha de coleta como
desabilitacao administrativa. Portas sem uso nao devem substituir os links de
internet realmente associados ao SD-WAN. Estado inativo ja persistido e mantido
na projecao do mapa; coleta administrativa separada continua pendente de evidencia
do campo/valor recebido. Nao foi criada regra para esconder queda como inativo.

## Validacao

Testes isolados por AST, sem importar o app real, acessar cofre ou equipamentos:
reproduzem WAN1/WAN2 sem IP e dmz/ha1 VIVO/ALGAR; verificam descoberta e leitura
canonica, exclusao de VPN/LAN, atualizacao rapida, mesmos links na pagina/detalhe/
mapa, cache reconciliado sem renovar medicoes alheias e remocao de falsos alertas.

Apos publicar/pull, combinar reinicio web SEM checklist/jobs ativos. Clicar
Atualizar links na Infra, aguardar conclusao e revisar pendencias do job. Conferir
REG_LEOPOLDO_B2 na Infra, detalhe regional e mapa apos nova requisicao: interfaces
e horarios devem corresponder ao resultado da coleta. Se ainda houver dados
antigos, registrar o erro dessa regional no job, nao editar JSON ou marcar
inativo manualmente para fazer o teste passar. Nao alterar PostgreSQL/rede.
