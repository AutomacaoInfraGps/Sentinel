# Sentinel - Automacao e Monitoramento de Infraestrutura

> Referencia viva do projeto. Atualizado em 01/09/2026. Toda alteracao
> funcional, operacional ou estrutural deve atualizar este arquivo no mesmo
> commit.

O Sentinel e uma aplicacao web Flask para automacao, consulta e monitoramento
da infraestrutura do Grupo GPS. Ele consolida regionais, servidores, VMs,
links, VPNs, switches, firewalls, licencas, APs UniFi, certificados, relatorios
e rotinas operacionais.

## Execucao principal

- `run_web_service.py`: inicia o Flask com Waitress na porta 5000.
- `web_config.py`: aplicacao web, rotas, cache e regras de negocio.
- `gerenciador_atualizacoes.py`: atualizacoes operacionais em background.
- `executar_tudo.py`: checklist e dashboard consolidado offline.
- `environment.json`: configuracao local e credenciais; nunca versionar.
- `estrutura_regionais.json`: cadastro local das regionais; nunca versionar.

Instalacao e inicializacao:

```powershell
pip install -r requirements.txt
.\restart_web_service.ps1
```

Alternativamente:

```powershell
python run_web_service.py
python executar_tudo.py --no-browser
```

A aplicacao fica disponivel em `http://localhost:5000`.

## Atualizacao e cache

O checklist executa o lote completo e gera a primeira fotografia/cache do dia.
O mapa funciona como atualizador operacional continuo:

- A thread de atualizacao roda a cada **3 minutos**.
- Links, VPNs, switches, firewalls, servidores e APs sao consultados.
- Somente registros alterados devem ser persistidos e registrados no historico.
- Infraestrutura, Regionais, Checklist e Mapa consomem a mesma base operacional,
  evitando estados diferentes entre as telas.
- O endpoint do mapa possui TTL configuravel por
  `MAPA_MONITORAMENTO_TTL_SECONDS`, com padrao de **300 segundos**.
- Caches especificos de integracoes continuam existindo para limitar chamadas
  externas; atualizacoes manuais podem forcar uma nova consulta.

## Modulos monitorados

### Regionais

A pagina principal consolida todos os componentes por regional. A tela de
detalhes apresenta servidores, links, switches, firewalls e acoes preventivas.

### Mapa

O mapa do Brasil mostra o estado operacional por regional, alertas e historico.
Os estados visuais sao normal, atencao, critico e manutencao. O valor tecnico
interno `warning` deve ser apresentado ao usuario como **atencao**.

O mapa embutido no checklist mantem seu visual proprio, mas recebe o mesmo
payload consolidado, estados e regras de dispositivos do mapa principal. Para
validar exatamente esse componente pelo cache sem gerar o checklist completo,
acesse `/mapa/checklist-preview`.

Tambem e possivel gerar um HTML estatico usando somente o ultimo cache:

```powershell
python tools/manual/gerar_preview_mapa_checklist.py
```

O resultado fica em `output/mapa_checklist_preview.html`.

O checklist final incorpora HTML, CSS, JavaScript e dados do mapa no proprio
arquivo. Ele pode ser aberto em outra maquina sem Flask, API ou arquivos da
pasta `output`. A fonte visual versionada fica em
`templates/mapa_checklist_base.html`; previews em `output/` sao descartaveis.
O CSS extraido do mapa e balanceado antes da incorporacao para nao interferir
nos cards da visao por dispositivo.

Na lateral do mapa do checklist, os contadores exibem somente total de
regionais e problemas operacionais: servidores, links, switches, APs e VPNs
offline, alem de firewalls offline e licencas de firewall a vencer. Cada
contador filtra as regionais correspondentes. Ao selecionar uma regional, a
lateral continua mostrando somente esses sete contadores de problema, sem
contadores online ou de admins. Os tooltips mostram no maximo dois problemas e
usam `...` quando existem alertas adicionais.

### Servidores e VMs

Monitora disponibilidade, servicos, seguranca e dados de VMs. Servidores em
manutencao no Zabbix nao devem ser tratados como offline.

### Switches

Usa a API do Zabbix e rotinas de backup. Diferencia online, offline, atencao,
manutencao e inativo. A manutencao e conciliada com as GMUDs ativas.
Quando um switch pertence a mais de um host group regional no Zabbix, grupos
explicitos no formato `REGIONAL ...` prevalecem sobre grupos tecnicos `REG_...`.

### Firewalls e licencas

Usa FortiManager e FortiGate para disponibilidade, modelo, serial, firmware e
licencas FortiCare. Disponibilidade e licenca possuem filtros independentes.
Quando uma consulta de licenca fica indisponivel, a ultima data valida pode ser
preservada sem transformar o equipamento automaticamente em offline.

### Links e VPNs

Consulta FortiManager/FortiGate, interfaces WAN e tuneis IPsec. Os dados sao
associados e persistidos na regional correspondente.
O campo `estado`/`uf` das regionais e salvo em `estrutura_regionais.json` e tem
prioridade sobre o mapeamento legado de estados ao posicionar a regional no mapa.
Quando ainda não existe UF salva, a tela de edição sugere automaticamente o
valor desse mapeamento legado, que pode ser alterado e persistido pelo usuário.

### APs UniFi

Coleta diretamente da controladora UniFi por `Unifi.Py`, incluindo modelo real,
firmware, clientes e metricas de radio. O IP e usado para conciliar manutencao
com o Zabbix e impedir falso offline. No checklist, APs conciliados como em
manutencao sao excluidos dos contadores, alertas e detalhes operacionais.

Os codigos de hardware retornados pela controladora sao convertidos para nomes
de exibicao em `services/unifi_models.py`; codigos desconhecidos sao mantidos.
A normalizacao tambem ocorre na leitura do cache operacional, permitindo que
registros anteriores sejam corrigidos sem aguardar a proxima rodada do mapa.

### Contatos e relatórios

O cadastro de e-mails usa uma planilha XLSX com `NOME_REGIONAL` para o padrão
SLA/Sentinel e `NOME_REG_FORTI` para a correspondência exata do relatório no
FortiAnalyzer. A API de mapeamento resolve qualquer uma das chaves e retorna os
destinatários, seus papéis e primeiros nomes. O editor altera contatos de
regionais existentes; novas linhas são incluídas pelo fluxo `Cadastrar regional`,
que também impede nomes SLA ou correspondências FortiAnalyzer duplicadas.
No Windows, o XLSX deve estar fechado no Excel e a conta do serviço web precisa
ter permissão de gravação na pasta configurada.

### Certificados, AD e relatorios

Inclui validade de certificados, replicacao do Active Directory, preventivas,
capturas de portais internos, dashboard consolidado e envio por Microsoft
Graph.

### SofIA

Assistente deterministica em `sofia/`, protegida por Flask-Login, limite de
requisicoes e auditoria. Responde com os dados ja carregados pelo Sentinel, sem
LLM externo.

## Integracoes

- Zabbix API
- UniFi Controller
- FortiManager, FortiGate e FortiAnalyzer
- Active Directory e WinRM
- Microsoft Graph
- GPS Amigo, Saturno, AppGate e portais internos

As credenciais ficam em `environment.json`. Use `environment.example.json` como
referencia segura de configuracao.

## Estrutura

```text
Automacao/
|-- run_web_service.py
|-- web_config.py
|-- gerenciador_atualizacoes.py
|-- executar_tudo.py
|-- services/              # servicos de dominio ativos
|-- clients/               # clientes de integracao
|-- auth/                  # autenticacao e autorizacao
|-- sofia/                 # assistente virtual
|-- templates/             # templates Jinja2
|-- static/                # CSS, JavaScript e imagens
|-- tests/unit/            # testes automatizados
|-- tests/manual/          # verificacoes sob demanda
|-- tools/manual/          # diagnosticos manuais
|-- tools/maintenance/     # manutencao do repositorio
|-- docs/                  # documentacao atual
|   `-- archive/           # material historico
|-- data/                  # dados locais de execucao
|-- output/                # dashboards, caches e relatorios
`-- logs/                  # logs da aplicacao
```

A lista de arquivos que ainda precisam permanecer na raiz e as areas legadas
estao em [docs/ESTRUTURA_PROJETO.md](docs/ESTRUTURA_PROJETO.md).

## Documentacao

- [Indice da documentacao](docs/README.md)
- [Estrutura atual](docs/ESTRUTURA_PROJETO.md)
- [Guia de configuracao](GUIA_CONFIGURACAO.md)
- [Autenticacao](README_AUTH.md)
- [Seguranca](GUIA_SEGURANCA.md)
- [Fluxo do desenvolvedor JR](GUIA_JR_HOMOLOGACAO.md)
- [Producao e homologacao](GUIA_AMBIENTES_PROD_HML.md)
- [Changelog](CHANGELOG.md)

## Seguranca e arquivos locais

Nunca versione `environment.json`, `estrutura_regionais.json`,
`admin_baseline.json`, credenciais, caches, HTML gerado ou ambientes virtuais.
Revise `git status` antes de cada commit.

Arquivos como `diagnostico.json`, `resultados_verificacao.json`,
`status_servidores.html` e `.venv/` sao locais e estao no `.gitignore`.

## Validacao antes do push

```powershell
python -m unittest discover -s tests/unit -p "*_test.py"
python -m py_compile run_web_service.py web_config.py gerenciador_atualizacoes.py executar_tudo.py
git diff --check
git status
```

O Waitress nao possui auto-reload. Reinicie o servico depois de alteracoes no
backend.

O mapa do checklist reutiliza a criticidade do mapa principal nas cores e no
posicionamento dos tooltips. Seus filtros e contadores continuam independentes.
Ao abrir uma regional, os equipamentos permanecem separados em cards
individuais dentro dos grupos de servidores, APs, switches, links, VPNs e
firewalls.
Os cards e os contadores da expansao sao hidratados pelo mesmo cache operacional
do mapa, evitando divergencia de status entre o alerta e o dispositivo.
Ao clicar em uma regional, ponto ou tooltip, o checklist isola a regional
selecionada na lista e no mapa ate o usuario voltar para a visao anterior.

## Manutencao da documentacao

- Atualize este `README.md` em toda mudanca relevante.
- Documentos ativos descrevem apenas o comportamento atual.
- Relatorios de implementacoes concluidas e versoes antigas ficam em
  `docs/archive/`.
- Antes de mover um arquivo, verifique imports, subprocessos, arquivos `.spec`,
  tarefas do Windows e referencias Markdown.
