# Sentinel - Automacao e Monitoramento de Infraestrutura

Sentinel e uma aplicacao web Flask para automacao, consulta e monitoramento de infraestrutura do Grupo GPS. O sistema centraliza regionais, servidores, links, switches, firewalls, VPNs, certificados, relatorios e rotinas operacionais em uma interface web unica.

O projeto roda principalmente em Windows, com Flask servido via Waitress, configuracoes locais em JSON e integracoes com FortiManager, FortiAnalyzer, Zabbix, UniFi, Microsoft Graph, Active Directory e portais internos.

## Visao Geral

- Aplicacao web principal: `web_config.py`
- Entrada do servico web: `run_web_service.py`
- Porta padrao: `5000`
- Templates: `templates/`
- Arquivos estaticos: `static/`
- Dados locais/runtime: `data/`, `output/`, `logs/`
- Configuracoes sensiveis: `environment.json` (nao deve ir para o Git)
- Estrutura das regionais: `estrutura_regionais.json` (nao deve ir para o Git)

## Funcionalidades Principais

### Regionais

- Cadastro e visualizacao de regionais.
- Servidores, VMs, links, switches e firewalls agrupados por regional.
- Tela principal em `/regionais`.
- Detalhe individual em `/regional/<codigo>`.

### Servidores e VMs

- Monitoramento de servidores regionais.
- Consulta de status, servicos e informacoes de VMs.
- Relatorios simples e completos.
- Dados organizados em estrutura hierarquica por regional.

### Links de Internet

- Consulta e exibicao de links por regional.
- Sincronizacao manual com FortiManager/FortiGate.
- Identificacao de interfaces WAN, IPs publicos, provedores, velocidades e status.
- A sincronizacao automatica ao abrir a tela de regionais foi desativada para reduzir consumo de API.

### Firewalls

- Tela em `/firewalls`.
- Consulta FortiGates via FortiManager.
- Exibe status, modelo, serial e licencas FortiCare.
- Usa cache local por ate 60 minutos para reduzir chamadas repetidas ao FortiManager.
- O botao "Atualizar Forti" forca nova consulta em tempo real.

### Monitor de Admins

- Tela em `/admin-logins`.
- Compara usuarios administradores atuais com a baseline aprovada em `admin_baseline.json`.
- Consulta:
  - FortiManager
  - FortiGates via proxy do FortiManager
  - FortiAnalyzer
  - Logs de eventos administrativos do FortiAnalyzer
- Usa cache local por ate 30 minutos.
- O botao "Atualizar Forti" forca nova consulta.

### Switches

- Tela em `/switches`.
- Integracao com Zabbix.
- Consulta status de switches, alertas e organizacao por regional.
- Usa `gerenciar_switches.py` e planilha/configuracao definida no ambiente.

### VPN IPsec

- Tela em `/vpn-ipsec`.
- Exibe tuneis VPN agrupados por regional.
- Dados obtidos via FortiManager/FortiGate.

### Antenas UniFi

- Telas de antenas UniFi e dashboards relacionados.
- Coleta por `Unifi.Py`.
- Agrupamento por site/regional.
- Exibe status de APs, clientes e informacoes operacionais.

### Certificados

- Telas de validade de certificados.
- Relatorios e templates para acompanhamento de certificados e discos.
- Exemplo de template: `templates/certificate_disk_report_acrab.json`.

### Relatorios e Rotinas

- Dashboard consolidado por `executar_tudo.py`.
- Relatorios de infraestrutura.
- Rotinas de replicacao AD.
- Capturas de portais internos, GPS Amigo, Saturno e AppGate.
- Envio de e-mails via Microsoft Graph.

### SofIA

- Assistente virtual integrada ao Sentinel.
- Modulo em `sofia/`.
- Ativacao por `environment.json`:

```json
"sofia": {
  "enabled": true
}
```

- A SofIA atualmente usa regras deterministicas, sem LLM externo.
- Ela responde sobre regionais, servidores, switches, links, VPNs, Zabbix e dashboard com base nos dados ja carregados pelo Sentinel.

## Arquitetura

```text
Automacao/
|-- web_config.py                  # Aplicacao Flask principal
|-- run_web_service.py             # Inicializacao Waitress
|-- config.py                      # Caminhos e carregamento do environment.json
|-- environment.example.json       # Exemplo seguro de configuracao
|-- environment.json               # Configuracao real local, nao versionada
|-- estrutura_regionais.json       # Regionais reais, nao versionado
|-- fortimanager_client.py         # Cliente FortiManager JSON-RPC
|-- fortianalyzer_client.py        # Cliente FortiAnalyzer JSON-RPC
|-- gerenciar_regionais.py         # Cadastro/estrutura de regionais
|-- gerenciar_switches.py          # Integracao Zabbix/switches
|-- gerenciar_vms.py               # Rotinas de VMs
|-- executar_tudo.py               # Dashboard consolidado
|-- gps_print.py                   # Capturas de portais
|-- sofia/                         # Assistente SofIA
|-- templates/                     # Templates HTML/Jinja2
|-- static/                        # CSS, JS, imagens e branding
|-- data/                          # Dados gerados em runtime
|-- output/                        # HTMLs, caches e relatorios
|-- logs/                          # Logs da aplicacao
```

## Configuracao

1. Copie ou gere um `environment.json` a partir de `environment.example.json`.
2. Configure credenciais e hosts dos sistemas usados:
   - Zabbix
   - FortiManager
   - FortiAnalyzer
   - UniFi
   - Microsoft Graph
   - Portais internos
3. Garanta que `environment.json`, `estrutura_regionais.json`, `admin_baseline.json` e arquivos com IPs/senhas continuem fora do Git.

Arquivos sensiveis ja devem estar protegidos no `.gitignore`.

## Execucao Local

Instale dependencias:

```bash
pip install -r requirements.txt
```

Inicie/reinicie o servico web:

```powershell
.\restart_web_service.ps1
```

Ou execute diretamente:

```bash
python run_web_service.py
```

Acesse:

```text
http://localhost:5000
```

## Execucao do Dashboard Consolidado

```bash
python executar_tudo.py
```

Para rodar sem abrir navegador:

```bash
python executar_tudo.py --no-browser
```

O dashboard consolidado gera arquivos em `output/` e tambem em pastas publicas configuradas em `config.py`.

## Fluxo de Publicacao

Na maquina local:

```bash
git status
git add .
git commit -m "feat: descricao da alteracao"
git pushall
```

No servidor:

```powershell
git pull
.\restart_web_service.ps1
```

O alias `git pushall` envia para os remotes configurados:

- `origin`
- `empresa`

## Cache e Consumo de API Forti

Para reduzir consumo no FortiManager/FortiAnalyzer:

- `/firewalls` usa cache por ate 60 minutos.
- `/admin-logins` usa cache por ate 30 minutos.
- Os botoes "Atualizar Forti" forcam consulta em tempo real.
- A sincronizacao automatica de links ao abrir regionais foi desativada.
- A sincronizacao de links continua disponivel manualmente.

Isso mantem as consultas funcionando, mas evita chamadas repetidas a cada navegacao.

## Seguranca

- Nunca commitar `environment.json`.
- Nunca commitar `estrutura_regionais.json` com IPs reais.
- Nunca commitar `admin_baseline.json` se contiver usuarios reais sensiveis.
- Evitar expor tokens, senhas, API keys e client secrets em codigo.
- Revisar `git status` antes de cada commit.

## Logs e Diagnostico

Locais principais:

- `logs/web_service.log`
- `logs/sofia_audit.jsonl`
- `logs/certificados.log`
- `output/dashboard_*_cache.json`
- `output/status_atualizacao.json`

Comandos uteis:

```bash
git status
python -m py_compile web_config.py
python verificar_dependencias.py
```

## Observacoes Operacionais

- O Waitress nao faz auto-reload: apos alterar backend, reinicie o servico.
- Alteracoes em templates geralmente exigem recarregar a pagina.
- Rotas que consultam Forti podem demorar dependendo da quantidade de dispositivos.
- O cache foi criado para aliviar consumo de API sem remover as consultas.

## Status Atual do Projeto

O Sentinel hoje e uma plataforma interna de automacao de infraestrutura com foco em:

- Operacao regional
- Monitoramento de rede
- Inventario e status de firewalls
- Controle de admins Forti
- Links, VPNs e switches
- Certificados e relatorios
- Assistente SofIA integrada

O projeto segue em evolucao e deve priorizar mudancas incrementais, mantendo compatibilidade com os dados locais e rotinas ja existentes.
