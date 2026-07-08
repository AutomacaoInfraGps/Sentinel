"""
Cliente FortiAnalyzer para o projeto Sentinel GPS.
Consulta logs de eventos de administração (criação/remoção de usuários admin nos FortiGates).
"""
import time
import requests
from datetime import datetime, timedelta, timezone


class FortiAnalyzerClient:
    """
    Comunicação com a API JSON-RPC do FortiAnalyzer via Bearer token.
    Compatível com FortiAnalyzer 7.x (apiver=3).
    """

    TIMEOUT_TASK = 40       # segundos esperando tarefa de log concluir
    SLEEP_POLL   = 2        # intervalo entre polls
    REQUEST_TIMEOUT = 30    # timeout HTTP

    def __init__(self, host: str, api_key: str, adom: str, verify_ssl: bool = False,
                 username: str = "", password: str = ""):
        self.api_url  = f"https://{host}/jsonrpc"
        self.api_key  = api_key
        self.adom     = adom
        self.verify_ssl = verify_ssl
        self.username = username or ""
        self.password = password or ""
        self._session = requests.Session()
        self._session.verify = verify_ssl
        self._session.headers.update({
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        })
        if not verify_ssl:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _rpc(self, payload: dict) -> dict:
        resp = self._session.post(self.api_url, json=payload, timeout=self.REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def _rpc_session(self, payload: dict, sessionid: str) -> dict:
        """Envia RPC com session ID (auth por usuário/senha)."""
        payload_with_session = {**payload, "session": sessionid}
        resp = self._session.post(self.api_url, json=payload_with_session,
                                  timeout=self.REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def _session_login(self) -> str:
        """Faz login com usuário/senha e retorna o session token."""
        payload = {
            "jsonrpc": "2.0",
            "id": "faz-login",
            "method": "exec",
            "params": [{
                "url": "/sys/login/user",
                "data": {"user": self.username, "passwd": self.password},
            }],
        }
        resp = self._session.post(self.api_url, json=payload, timeout=self.REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        # Formato: {"session": "...", "result": [{"status": {"code": 0}}]}
        result = (data.get("result") or [{}])[0]
        code = (result.get("status") or {}).get("code", -1)
        if code != 0:
            msg = (result.get("status") or {}).get("message", "Falha no login")
            raise PermissionError(f"FAZ login falhou: {msg} (code={code})")
        session = data.get("session")
        if not session:
            raise PermissionError("FAZ login nao retornou session token")
        return session

    def _session_logout(self, sessionid: str) -> None:
        """Encerra sessão no FortiAnalyzer."""
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": "faz-logout",
                "method": "exec",
                "params": [{"url": "/sys/logout"}],
                "session": sessionid,
            }
            self._session.post(self.api_url, json=payload, timeout=10)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Busca assíncrona de logs (cria task → poll → retorna logs)
    # Suporta dois formatos de resposta:
    #   v1 (chave logs): result[0]["data"]["taskid"] / result[0]["data"]["logs"]
    #   v2 (chave main): result["tid"]               / result["data"]
    # ------------------------------------------------------------------
    def _create_log_task(self, logtype: str, filter_str: str,
                         start: datetime, end: datetime, limit: int = 500) -> str:
        payload = {
            "jsonrpc": "2.0",
            "id": "sentinel-task",
            "method": "add",
            "params": [{
                "apiver": 3,
                "logtype": logtype,
                "time-order": "desc",
                "time-range": {
                    "start": start.strftime("%Y-%m-%dT%H:%M:%S"),
                    "end":   end.strftime("%Y-%m-%dT%H:%M:%S"),
                },
                "filter": filter_str,
                "device": [{"devid": "All_Devices"}],
                "url": f"/logview/adom/{self.adom}/logsearch",
            }],
        }
        result = self._rpc(payload)
        raw = result.get("result", {})
        # Formato v2: {"result": {"tid": N}}
        if isinstance(raw, dict):
            tid = raw.get("tid") or raw.get("taskid")
            if tid:
                return str(tid)
        # Formato v1: {"result": [{"data": {"taskid": "..."}}]}
        if isinstance(raw, list) and raw:
            tid = raw[0].get("data", {}).get("taskid")
            if tid:
                return str(tid)
        raise RuntimeError(f"FortiAnalyzer: falha ao criar task de log — {result}")

    def _poll_log_task(self, task_id: str, limit: int = 500) -> list:
        deadline = time.time() + self.TIMEOUT_TASK
        while True:
            payload = {
                "jsonrpc": "2.0",
                "id": "sentinel-get",
                "method": "get",
                "params": [{
                    "apiver": 3,
                    "offset": 0,
                    "limit": limit,
                    "url": f"/logview/adom/{self.adom}/logsearch/{task_id}",
                }],
            }
            result = self._rpc(payload)
            raw = result.get("result", {})

            # Formato v2: result é dict direto
            if isinstance(raw, dict):
                status = raw.get("status", {})
                # Considera concluído se status.code == 0 ou não está "running"
                if isinstance(status, dict) and status.get("code", -1) == 0:
                    return raw.get("data", [])
                if isinstance(status, str) and status != "running":
                    return raw.get("data", raw.get("logs", []))
                # Ainda rodando
                if time.time() > deadline:
                    raise TimeoutError(f"FortiAnalyzer: timeout aguardando task {task_id}")
                time.sleep(self.SLEEP_POLL)
                continue

            # Formato v1: result é lista
            if isinstance(raw, list):
                data = raw[0].get("data", {}) if raw else {}
                if data.get("status") == "running":
                    if time.time() > deadline:
                        raise TimeoutError(f"FortiAnalyzer: timeout aguardando task {task_id}")
                    time.sleep(self.SLEEP_POLL)
                    continue
                return data.get("logs", data.get("data", []))

            if time.time() > deadline:
                raise TimeoutError(f"FortiAnalyzer: timeout aguardando task {task_id}")
            time.sleep(self.SLEEP_POLL)

    def search_logs(self, logtype: str, filter_str: str,
                    minutes_back: int = 1440, limit: int = 500) -> list:
        """Executa uma busca de logs e retorna a lista de eventos."""
        end   = datetime.now(timezone.utc)
        start = end - timedelta(minutes=minutes_back)
        task_id = self._create_log_task(logtype, filter_str, start, end, limit)
        return self._poll_log_task(task_id, limit) or []

    # ------------------------------------------------------------------
    # Consultas específicas de administração
    # ------------------------------------------------------------------
    def get_admin_events(self, minutes_back: int = 1440, limit: int = 1000) -> list:
        """
        Retorna eventos de criação/edição/remoção de usuários admin nos FortiGates,
        FortiManager e FortiAnalyzer via FortiAnalyzer log search.
        Campos reais confirmados: cfgpath='system.admin', cfgobj=usuario, action=Add/Delete/Edit
        """
        # 'logdesc = "Object attribute configured"' cobre Add/Edit/Delete de qualquer config.
        # Filtramos por cfgpath == 'system.admin' em Python após receber os logs.
        filter_str = 'logdesc = "Object attribute configured"'
        logs = self.search_logs("event", filter_str, minutes_back=minutes_back, limit=limit)

        import urllib.parse
        eventos = []
        for log in logs:
            if not isinstance(log, dict):
                continue
            # Filtra apenas eventos relacionados a system.admin
            cfgpath = log.get("cfgpath", "")
            if cfgpath != "system.admin":
                continue
            action_raw = (log.get("action") or "").lower()
            if action_raw not in ("add", "delete", "edit", "modify"):
                continue
            # msg pode estar URL-encoded
            msg_raw = log.get("msg", "")
            try:
                msg = urllib.parse.unquote(msg_raw)
            except Exception:
                msg = msg_raw
            eventos.append({
                "timestamp":   log.get("itime") or (log.get("date", "") + " " + log.get("time", "")),
                "device_id":   log.get("devid", ""),
                "device_name": log.get("devname", ""),
                "usuario_op":  log.get("user", ""),      # quem fez a operação
                "acao":        action_raw,
                "objeto":      log.get("cfgobj", ""),    # usuário afetado (campo correto)
                "msg":         msg,
                "nivel":       log.get("level", "information"),
                "interface":   log.get("ui", ""),        # GUI(IP) ou SSH
            })
        return eventos

    def get_current_admins_via_fmg_proxy(self, fmg_client, adom: str, device_name: str) -> list:
        """
        Usa o proxy do FortiManager para buscar a lista atual de admins de um FortiGate.
        Retorna lista de nomes de usuários admin.
        """
        payload = {
            "id": 1,
            "method": "exec",
            "params": [{
                "url": "/sys/proxy/json",
                "data": {
                    "target": [f"adom/{adom}/device/{device_name}"],
                    "action": "get",
                    "resource": "/api/v2/cmdb/system/admin",
                },
            }],
            "session": fmg_client.sessionid,
        }
        resp = fmg_client.session.post(fmg_client.base_url, json=payload, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        outer = data.get("result", [{}])[0]
        proxy_list = outer.get("data", [])
        if not proxy_list:
            return []

        entry = proxy_list[0] if isinstance(proxy_list, list) else proxy_list
        status = entry.get("status", {})
        if isinstance(status, dict) and status.get("code", 0) != 0:
            return []  # device offline

        response_body = entry.get("response", {})
        admins_raw = response_body.get("results", []) if isinstance(response_body, dict) else []
        return [a.get("name", "") for a in admins_raw if isinstance(a, dict) and a.get("name")]

    # ------------------------------------------------------------------
    # Admins do próprio FortiAnalyzer
    # ------------------------------------------------------------------
    def get_fortianalyzer_admins_status(self) -> dict:
        """Retorna admins visiveis e informa se a conta REST ve a lista completa.
        Se username/password configurados, usa sessão para ver todos os admins locais.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": "faz-admins-status",
            "method": "get",
            "params": [{"url": "/cli/global/system/admin/user"}],
        }

        # --- Tenta auth por sessão (usuario+senha) para ver admins locais ---
        if self.username and self.password:
            sessionid = None
            try:
                sessionid = self._session_login()
                result = self._rpc_session(payload, sessionid)
                first_result = (result.get("result") or [{}])[0]
                status = first_result.get("status") or {}
                if status.get("code", 0) != 0:
                    raise PermissionError(status.get("message", "Sem permissao"))
                users = first_result.get("data", [])
                if isinstance(users, list):
                    admins = sorted(set(
                        u.get("userid", u.get("name", "")).strip()
                        for u in users if isinstance(u, dict) and (u.get("userid") or u.get("name"))
                    ))
                    # Mesmo via sessão, se só retornou contas REST API (user_type=8),
                    # significa que admins LDAP/locais não são visíveis por este método.
                    only_rest_accounts = bool(users) and all(
                        int(u.get("user_type", -1)) == 8 for u in users if isinstance(u, dict)
                    )
                    return {
                        "admins": admins,
                        "visibilidade_completa": True,
                        "apenas_contas_api": only_rest_accounts,
                        "motivo": (
                            "Somente contas REST API visíveis via sessão. "
                            "Admins LDAP/locais não são expostos por este método — "
                            "alterações são monitoradas via logs de evento do FortiAnalyzer."
                        ) if only_rest_accounts else "",
                    }
            except Exception as exc:
                return {"admins": [], "visibilidade_completa": False,
                        "apenas_contas_api": False,
                        "motivo": f"Falha no login por sessao: {exc}"}
            finally:
                if sessionid:
                    self._session_logout(sessionid)

        # --- Fallback: Bearer token (ve somente contas REST) ---
        try:
            result = self._rpc(payload)
            first_result = (result.get("result") or [{}])[0]
            status = first_result.get("status") or {}
            if status.get("code", 0) != 0:
                return {
                    "admins": [],
                    "visibilidade_completa": False,
                    "motivo": status.get("message") or "API sem permissao para listar administradores.",
                }

            users = first_result.get("data", [])
            if isinstance(users, list):
                admins = sorted(set(
                    u.get("userid", u.get("name", "")).strip()
                    for u in users if isinstance(u, dict) and (u.get("userid") or u.get("name"))
                ))
                only_rest_accounts = bool(users) and all(
                    int(u.get("user_type", -1)) == 8 for u in users if isinstance(u, dict)
                )
                if only_rest_accounts:
                    return {
                        "admins": admins,
                        "visibilidade_completa": True,
                        "apenas_contas_api": True,
                        "motivo": (
                            "Somente contas REST API sao visiveis via Bearer token. "
                            "Admins locais nao sao expostos por este metodo — "
                            "alteracoes sao monitoradas via logs de evento do FortiAnalyzer."
                        ),
                    }
                return {"admins": admins, "visibilidade_completa": True, "apenas_contas_api": False, "motivo": ""}
        except Exception as exc:
            return {
                "admins": [],
                "visibilidade_completa": False,
                "motivo": f"Falha ao consultar administradores: {exc}",
            }
        return {
            "admins": [],
            "visibilidade_completa": False,
            "motivo": "Resposta da API sem uma lista valida de administradores.",
        }

    def get_fortianalyzer_admins(self) -> list:
        """
        Retorna lista de userids admin do próprio FortiAnalyzer.
        Usa o endpoint /cli/global/system/admin/user via JSON-RPC.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": "faz-admins",
            "method": "get",
            "params": [{"url": "/cli/global/system/admin/user"}],
        }
        try:
            result = self._rpc(payload)
            users = result.get("result", [{}])[0].get("data", [])
            if isinstance(users, list):
                return sorted(set(
                    u.get("userid", u.get("name", "")).strip()
                    for u in users if isinstance(u, dict) and (u.get("userid") or u.get("name"))
                ))
        except Exception:
            pass
        return []

