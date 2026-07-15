# 🛡️ Sentinel - Automação e Monitoramento de Infraestrutura

O **Sentinel** é uma aplicação web Flask para automação, consulta e monitoramento de infraestrutura do **Grupo GPS**. O sistema centraliza regionais, servidores, links, switches, firewalls, VPNs, certificados, relatórios e rotinas operacionais em uma interface web única.

O projeto roda principalmente em Windows, com Flask servido via **Waitress**, configurações locais em JSON e integrações com **FortiManager**, **FortiAnalyzer**, **Zabbix**, **UniFi**, **Microsoft Graph**, **Active Directory** e portais internos.

## 🚀 Visão Geral

- 🌐 Aplicação web principal: `web_config.py`
- ⚙️ Entrada do serviço web: `run_web_service.py`
- 🔌 Porta padrão: `5000`
- 🧩 Templates: `templates/`
- 🎨 Arquivos estáticos: `static/`
- 📁 Dados locais/runtime: `data/`, `output/`, `logs/`
- 🔐 Configurações sensíveis: `environment.json` (não deve ir para o Git)
- 🏢 Estrutura das regionais: `estrutura_regionais.json` (não deve ir para o Git)

## 📚 Documentação de Apoio

Além deste README principal, o projeto tem documentos específicos para operação, configuração e manutenção:

- 📘 [Guia de Configuração](GUIA_CONFIGURACAO.md) - configuração geral do ambiente.
- 🔐 [README de Autenticação](README_AUTH.md) - autenticação e controle de acesso.
- 🧱 [Estrutura V2](README_ESTRUTURA_V2.md) - organização da estrutura hierárquica.
- 🛡️ [Guia de Segurança](GUIA_SEGURANCA.md) - cuidados com credenciais e arquivos sensíveis.
- 🧪 [Guia JR Homologação](GUIA_JR_HOMOLOGACAO.md) - fluxo de homologação.
- 🏭 [Ambientes Produção/Homologação](GUIA_AMBIENTES_PROD_HML.md) - operação entre ambientes.
- 📦 [Guia de Compilação EXE](GUIA_COMPILACAO_EXE.md) - empacotamento/compilação.
- 📝 [Changelog](CHANGELOG.md) - histórico de mudanças.
- 📁 [Docs](docs/README.md) - documentação complementar na pasta `docs/`.

Observação: arquivos pessoais de contexto para IA, como `COPILOT_CONTEXT.md`, devem ficar somente locais e não devem ser versionados.

## 🧭 Funcionalidades Principais

### 🏢 Regionais

- Cadastro e visualização de regionais.
- Servidores, VMs, links, switches e firewalls agrupados por regional.
- Tela principal em `/regionais`.
- Detalhe individual em `/regional/<codigo>`.

### 🖥️ Servidores e VMs

- Monitoramento de servidores regionais.
- Consulta de status, serviços e informações de VMs.
- Relatórios simples e completos.
- Dados organizados em estrutura hierárquica por regional.

### 🌐 Links de Internet

- Consulta e exibição de links por regional.
- Sincronização manual com FortiManager/FortiGate.
- Identificação de interfaces WAN, IPs públicos, provedores, velocidades e status.
- A sincronização automática ao abrir a tela de regionais foi desativada para reduzir consumo de API.

### 🔥 Firewalls

- Tela em `/firewalls`.
- Consulta FortiGates via FortiManager.
- Exibe status, modelo, serial e licenças FortiCare.
- Usa cache local por até **60 minutos** para reduzir chamadas repetidas ao FortiManager.
- O botão **Atualizar Forti** força nova consulta em tempo real.

### 👤 Monitor de Admins

- Tela em `/admin-logins`.
- Compara usuários administradores atuais com a baseline aprovada em `admin_baseline.json`.
- Consulta FortiManager, FortiGates via proxy do FortiManager, FortiAnalyzer e logs administrativos.
- Usa cache local por até **30 minutos**.
- O botão **Atualizar Forti** força nova consulta.

### 🔌 Switches

- Tela em `/switches`.
- Integração com Zabbix.
- Consulta status de switches, alertas e organização por regional.
- Usa `gerenciar_switches.py` e planilha/configuração definida no ambiente.

### 🔐 VPN IPsec

- Tela em `/vpn-ipsec`.
- Exibe túneis VPN agrupados por regional.
- Dados obtidos via FortiManager/FortiGate.

### 📡 Antenas UniFi

- Telas de antenas UniFi e dashboards relacionados.
- Coleta por `Unifi.Py`.
- Agrupamento por site/regional.
- Exibe status de APs, clientes e informações operacionais.

### 📜 Certificados

- Telas de validade de certificados.
- Relatórios e templates para acompanhamento de certificados e discos.
- Exemplo de template: `templates/certificate_disk_report_acrab.json`.

### 📊 Relatórios e Rotinas

- Dashboard consolidado por `executar_tudo.py`.
- Relatórios de infraestrutura.
- Rotinas de replicação AD.
- Capturas de portais internos, GPS Amigo, Saturno e AppGate.
- Envio de e-mails via Microsoft Graph.

### 🤖 SofIA

- Assistente virtual integrada ao Sentinel.
- Módulo em `sofia/`.
- Ativação por `environment.json`:

```json
"sofia": {
  "enabled": true
}
```

- A SofIA atualmente usa regras determinísticas, sem LLM externo.
- Ela responde sobre regionais, servidores, switches, links, VPNs, Zabbix e dashboard com base nos dados já carregados pelo Sentinel.

## 🧱 Arquitetura

```text
Automacao/
|-- web_config.py                  # Aplicação Flask principal
|-- run_web_service.py             # Inicialização Waitress
|-- config.py                      # Caminhos e carregamento do environment.json
|-- environment.example.json       # Exemplo seguro de configuração
|-- environment.json               # Configuração real local, não versionada
|-- estrutura_regionais.json       # Regionais reais, não versionado
|-- fortimanager_client.py         # Cliente FortiManager JSON-RPC
|-- fortianalyzer_client.py        # Cliente FortiAnalyzer JSON-RPC
|-- gerenciar_regionais.py         # Cadastro/estrutura de regionais
|-- gerenciar_switches.py          # Integração Zabbix/switches
|-- gerenciar_vms.py               # Rotinas de VMs
|-- executar_tudo.py               # Dashboard consolidado
|-- gps_print.py                   # Capturas de portais
|-- sofia/                         # Assistente SofIA
|-- templates/                     # Templates HTML/Jinja2
|-- static/                        # CSS, JS, imagens e branding
|-- data/                          # Dados gerados em runtime
|-- output/                        # HTMLs, caches e relatórios
|-- logs/                          # Logs da aplicação
```

## ⚙️ Configuração

1. Copie ou gere um `environment.json` a partir de `environment.example.json`.
2. Configure credenciais e hosts dos sistemas usados:
   - Zabbix
   - FortiManager
   - FortiAnalyzer
   - UniFi
   - Microsoft Graph
   - Portais internos
3. Garanta que `environment.json`, `estrutura_regionais.json`, `admin_baseline.json` e arquivos com IPs/senhas continuem fora do Git.

Arquivos sensíveis já devem estar protegidos no `.gitignore`.

## ▶️ Execução Local

Instale dependências:

```bash
pip install -r requirements.txt
```

Inicie/reinicie o serviço web:

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

## 📊 Dashboard Consolidado

```bash
python executar_tudo.py
```

Para rodar sem abrir navegador:

```bash
python executar_tudo.py --no-browser
```

O dashboard consolidado gera arquivos em `output/` e também em pastas públicas configuradas em `config.py`.

## 🧯 Cache e Consumo de API Forti

Para reduzir consumo no FortiManager/FortiAnalyzer:

- `/firewalls` usa cache por até **60 minutos**.
- `/admin-logins` usa cache por até **30 minutos**.
- Os botões **Atualizar Forti** forçam consulta em tempo real.
- A sincronização automática de links ao abrir regionais foi desativada.
- A sincronização de links continua disponível manualmente.

Isso mantém as consultas funcionando, mas evita chamadas repetidas a cada navegação.

## 🔒 Segurança

- Nunca commitar `environment.json`.
- Nunca commitar `estrutura_regionais.json` com IPs reais.
- Nunca commitar `admin_baseline.json` se contiver usuários reais sensíveis.
- Evitar expor tokens, senhas, API keys e client secrets em código.
- Revisar `git status` antes de cada commit.

## 🧾 Logs e Diagnóstico

Locais principais:

- `logs/web_service.log`
- `logs/sofia_audit.jsonl`
- `logs/certificados.log`
- `output/dashboard_*_cache.json`
- `output/status_atualizacao.json`

Comandos úteis:

```bash
git status
python -m py_compile web_config.py
python tools/manual/verificar_dependencias.py
```

## 🛠️ Observações Operacionais

- O Waitress não faz auto-reload: após alterar backend, reinicie o serviço.
- Alterações em templates geralmente exigem recarregar a página.
- Rotas que consultam Forti podem demorar dependendo da quantidade de dispositivos.
- O cache foi criado para aliviar consumo de API sem remover as consultas.

## ✅ Status Atual do Projeto

O Sentinel hoje é uma plataforma interna de automação de infraestrutura com foco em:

- Operação regional
- Monitoramento de rede
- Inventário e status de firewalls
- Controle de admins Forti
- Links, VPNs e switches
- Certificados e relatórios
- Assistente SofIA integrada

O projeto segue em evolução e deve priorizar mudanças incrementais, mantendo compatibilidade com os dados locais e rotinas já existentes.

