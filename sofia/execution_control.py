"""Server-only control of one known SofIA n8n execution."""

import os
import re
from urllib.parse import urlsplit, urlunsplit

import requests

from .n8n_client import SofiaN8nError, _configured_url


def configured_workflow():
    value = os.environ.get("SENTINEL_SOFIA_N8N_WORKFLOW_ID", "").strip()
    if not value:
        raise SofiaN8nError("Workflow de cancelamento nao configurado")
    return value


def execution_id(value):
    value = str(value)
    if not re.fullmatch(r"[1-9][0-9]{0,19}", value):
        raise ValueError("Identificador da execucao invalido")
    return value


def _api_config():
    webhook = urlsplit(_configured_url())
    prefix = webhook.path.split("/webhook/", 1)[0] if "/webhook/" in webhook.path else ""
    default = urlunsplit((webhook.scheme, webhook.netloc, prefix + "/api/v1", "", ""))
    base = os.environ.get("SENTINEL_SOFIA_N8N_API_URL", default).strip().rstrip("/")
    parsed = urlsplit(base)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or
            parsed.username or parsed.password or parsed.query or parsed.fragment or
            (parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"})):
        raise SofiaN8nError("URL de controle do n8n invalida")
    key = os.environ.get("SENTINEL_SOFIA_N8N_API_KEY", "").strip()
    if len(key) < 20:
        raise SofiaN8nError("Controle de execucoes nao configurado")
    return base, {"X-N8N-API-KEY": key}


def stop_execution(value):
    value = execution_id(value)
    workflow = configured_workflow()
    base, headers = _api_config()
    try:
        response = requests.get(f"{base}/executions/{value}", params={"includeData": "false"},
                                headers=headers, timeout=(2, 3), allow_redirects=False)
        if response.status_code != 200:
            raise SofiaN8nError(f"Verificacao da execucao no n8n: HTTP {response.status_code}")
        data = response.json()
        if not isinstance(data, dict) or str(data.get("workflowId")) != workflow:
            raise SofiaN8nError("Execucao fora do workflow autorizado")
        if data.get("status") == "canceled":
            return True
        if data.get("status") not in {"new", "running", "waiting"}:
            return False
        response = requests.post(f"{base}/executions/{value}/stop", headers=headers,
                                 timeout=(2, 3), allow_redirects=False)
        if response.status_code != 200:
            raise SofiaN8nError(f"Parada da execucao no n8n: HTTP {response.status_code}")
        data = response.json()
        return isinstance(data, dict) and data.get("status") == "canceled"
    except (requests.RequestException, ValueError) as exc:
        raise SofiaN8nError("Falha no controle da execucao do n8n") from exc


def cancellation_diagnostics(value=None):
    """Inspect configuration or one execution without exposing keys or stopping it."""
    report = {
        "workflow_configured": bool(os.environ.get("SENTINEL_SOFIA_N8N_WORKFLOW_ID", "").strip()),
        "api_key_configured": len(os.environ.get("SENTINEL_SOFIA_N8N_API_KEY", "").strip()) >= 20,
    }
    try:
        workflow = configured_workflow()
        base, headers = _api_config()
        report["configuration_valid"] = True
        if value is not None:
            identifier = execution_id(value)
            response = requests.get(
                f"{base}/executions/{identifier}", params={"includeData": "false"},
                headers=headers, timeout=(2, 3), allow_redirects=False,
            )
            report["http_status"] = response.status_code
            if response.status_code == 200:
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Invalid execution response")
                report["workflow_matches"] = str(data.get("workflowId")) == workflow
                status = data.get("status")
                report["execution_status"] = status if status in {
                    "new", "running", "waiting", "canceled", "success", "error", "crashed", "unknown"
                } else "unknown"
    except SofiaN8nError as exc:
        report["configuration_valid"] = False
        report["error"] = str(exc)
    except (requests.RequestException, ValueError):
        report["error"] = "Falha ao consultar metadados da execucao; nenhum cancelamento solicitado."
    return report


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Diagnostico de cancelamento sem revelar chaves nem parar execucoes.")
    parser.add_argument("--execution-id", help="ID de uma execucao da SofIA para consultar somente metadados.")
    args = parser.parse_args()
    print(json.dumps(cancellation_diagnostics(args.execution_id), ensure_ascii=False, indent=2))
