# Contexto do Projeto Sentinel — para GitHub Copilot

> **Instrução para o Copilot:** Leia este arquivo ao iniciar uma nova sessão neste repositório para entender a arquitetura completa do sistema antes de fazer qualquer alteração.

---

## Visão Geral

**Sentinel** é um sistema de automação e monitoramento de infraestrutura de rede para o **Grupo GPS**. É uma aplicação web Flask servida via **Waitress** (8 threads) na porta **5000**, com entry point `run_web_service.py` e lógica principal em `web_config.py`.

- URL interna: `http://10.254.12.63:5000`
- Reiniciar o serviço após mudanças no backend (não há auto-reload): `restart_server.py`

---

## Stack Técnica

| Componente | Tecnologia |
|---|---|
| Framework web | Flask + Waitress (porta 5000) |
| Frontend | Bootstrap 5 + Jinja2 templates |
| Dados em runtime | JSON files em `data/` (via `data_store.py`) |
| Autenticação web | Sessão Flask + `auth_ad.py` (Active Directory) |
| Configurações/credenciais | `environment.json` (no .gitignore) |

---

## Estrutura de Arquivos Principais

```
web_config.py          # App Flask principal — todas as rotas e lógica
run_web_service.py     # Entry point do servidor Waitress
config.py              # Carrega environment.json → ENV_CONFIG
data_store.py          # load_data() / save_data() — JSON em data/
fortianalyzer_client.py  # Cliente FAZ JSON-RPC (Bearer token + session auth)
fortimanager_client.py   # Cliente FMG JSON-RPC (session auth)
Unifi.Py               # Coleta dados UniFi → salva em data/unifi.json
auth_ad.py             # Autenticação Active Directory
sofia/                 # Módulo chatbot Sofia (engine determinístico)
templates/             # Templates Jinja2 (.html)
data/                  # Dados de runtime em JSON (no .gitignore)
environment.json       # Credenciais e configurações (NO .gitignore — nunca commitar)
admin_baseline.json    # Baseline de admins aprovados por dispositivo (no .gitignore)
estrutura_regionais.json # Estrutura de regionais com IPs (no .gitignore)
```

---

## Módulos do Sistema

### 1. Regionais
- Página: `/regionais`
- Cada regional tem FortiGates, servidores/VMs, switches, links de internet
- Dados em `estrutura_regionais.json` (não commitado — tem IPs reais)
- VMs monitoradas via WinRM/TrustedHosts, não iDRAC/Redfish

### 2. Infraestrutura — Firewalls
- Página: `/firewalls`
- Dados via FortiManager API (proxy para FortiGates)
- Template: `templates/firewalls.html`

### 3. Monitor de Admins (`/admin-logins`)
- Compara lista atual de admins com `admin_baseline.json`
- **FortiGates**: via FMG proxy (`get_fortigate_admins`) — paralelo com `ThreadPoolExecutor(10)`
- **FortiManager**: via `/cli/global/system/admin/user`
- **FortiAnalyzer**: Bearer token vê só contas REST (badge "Monitoramento limitado")
  - Se `username`+`password` preenchidos em `environment.json["fortianalyzer"]` → login por sessão → vê todos os admins locais
  - Fallback automático para Bearer token se sem credenciais
- **Histórico de eventos**: `get_admin_events()` busca logs FAZ para criações/deleções

### 4. Antenas UniFi (`/antenas`)
- Dados gerados por `Unifi.Py` → salvo em `data/unifi.json`
- Agrupados por site/regional via `sites_agrupados` na rota
- Contadores clicáveis filtram por status (online/offline)
- Análise de interferência co-canal 5GHz por regional

### 5. Switches (`/switches`)
- Dados do Zabbix API
- Gerenciado por `gerenciar_switches.py`

### 6. VPN IPsec (`/vpn-ipsec`)
- Dados via FortiManager proxy

### 7. Links de Internet
- Exibe IPs públicos via FortiManager SD-WAN
- Links sem IP público: usar `addressing_mode` das interfaces (mode=2 = PPPoE)

### 8. Sofia (Chatbot)
- Módulo: `sofia/`
- Engine determinístico (sem LLM), acesso read-only a dados de regionais/switches
- Rota: `GET/POST /api/sofia/chat` (Blueprint, rate limited 20req/60s, requer auth)

---

## FortiAnalyzer Client (`fortianalyzer_client.py`)

```python
FortiAnalyzerClient(
    host="10.254.12.34",
    api_key="...",         # Bearer token para logs
    adom="GPS_UNIDADES",
    verify_ssl=False,
    username="",           # Opcional: admin local para listar todos admins
    password="",           # Opcional: senha do admin local
)
```

**Métodos principais:**
- `search_logs(logtype, filter_str, minutes_back, limit)` — busca async via task
- `get_admin_events(minutes_back, limit)` — eventos de add/delete/edit em `system.admin`
- `get_fortianalyzer_admins_status()` — lista admins FAZ (sessão se tiver user/pass, Bearer se não)

**Limitação conhecida:** Bearer token (REST API account `user_type=8`) só vê outras contas REST via `/cli/global/system/admin/user`. Para ver admins locais, precisa de `username`+`password` de admin local.

---

## FortiManager Client (`fortimanager_client.py`)

- Auth: session-based (user/password via `/sys/login/user`)
- Suporta também Bearer token se `api_key` configurado
- Proxy para FortiGates via `/sys/proxy/json`

---

## `environment.json` — Estrutura de Credenciais (NÃO commitar)

```json
{
  "fortianalyzer": {
    "host": "...",
    "api_key": "...",
    "api_key_logs": "...",
    "adom": "GPS_UNIDADES",
    "username": "",         // admin local FAZ (opcional)
    "password": "",         // senha admin FAZ (opcional)
    "admin_monitor_minutes_back": 1440
  },
  "fortimanager": { "host": "...", "username": "...", "password": "..." },
  "unifi_controller": { "host": "...", "port": 8443, "username": "...", "password": "..." },
  "zabbix": { "url": "...", "token": "..." },
  "microsoft_graph": { "tenant_id": "...", "client_id": "...", "client_secret": "..." },
  "email_provider": "graph"
}
```

---

## `admin_baseline.json` — Estrutura (NÃO commitar)

```json
{
  "__fortimanager__": ["admin", "admin.pimentel", ...],
  "__fortianalyzer__": ["admin", "api.monitoramento", ...],
  "FGT_NOME_DISPOSITIVO": ["admin", ...]
}
```

---

## Convenções de Código

- **Rotas Flask**: decorador `@app.route` + `@login_required` em `web_config.py`
- **Cache de dashboard**: `_salvar_cache_dashboard(chave, dados)` para updates em background
- **Dados de runtime**: sempre via `load_data("componente")` / `save_data("componente", dados)`
- **Credenciais**: sempre de `ENV_CONFIG = config.ENV_CONFIG` — nunca hardcoded
- **Templates**: `templates/*.html` extendem `base.html`

---

## Pontos de Atenção

1. **Reiniciar servidor** após qualquer mudança em `web_config.py` — Waitress não faz auto-reload
2. **`environment.json`** nunca vai para o git — tem todas as credenciais e IPs de infraestrutura
3. **`estrutura_regionais.json`** nunca vai para o git — tem IPs reais de FortiGates por regional
4. **FAZ admin listing**: Bearer token só vê REST accounts — para visibilidade total, configurar `username`/`password` no `environment.json["fortianalyzer"]`
5. **Threads**: Monitor de Admins usa `ThreadPoolExecutor(10)` para queries paralelas — não aumentar demais pois o FMG tem limite de sessões simultâneas
