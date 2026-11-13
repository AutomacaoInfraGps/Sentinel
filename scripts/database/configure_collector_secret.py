"""Provision only the operational collector password in the existing DPAPI vault."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.secret_store import JsonSecretStore, SecretStoreError  # noqa: E402
from scripts.database.import_firewall_cache import (  # noqa: E402
    ImportErrorSafe, _database_error, _read_password,
)


COLLECTOR_REFERENCE = "sentinel/postgresql/collector/password"
EXPECTED_ACCOUNT = "galaxia\\admin.pimentel"


def verify_windows_identity():
    if os.name != "nt" or os.environ.get("COMPUTERNAME", "").upper() != "RIGEL":
        raise ImportErrorSafe("Execute esta preparacao somente no Rigel.")
    identity = subprocess.run(
        [str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "whoami.exe")],
        check=True, capture_output=True, text=True,
    ).stdout.strip().casefold()
    if identity != EXPECTED_ACCOUNT:
        raise ImportErrorSafe("Execute como GALAXIA\\admin.pimentel, a identidade atual dos processos do Sentinel.")


def validate_connection(password, connect):
    try:
        with connect(
            host="127.0.0.1", port=5433, dbname="sentinel",
            user="sentinel_collector", password=password, connect_timeout=10,
            application_name="sentinel_collector_secret_setup",
            options="-c search_path=pg_catalog -c default_transaction_read_only=on",
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_user, current_database(), inet_server_port()")
                if cursor.fetchone() != ("sentinel_collector", "sentinel", 5433):
                    raise ImportErrorSafe("Identidade SQL ou destino divergente. Credencial nao sera gravada.")
    except ImportErrorSafe:
        raise
    except Exception as exc:
        raise _database_error("conexao", exc) from None


def configure(password, *, store, connect):
    if store.contains(COLLECTOR_REFERENCE):
        raise ImportErrorSafe("A referencia do coletor ja existe. Nenhuma credencial foi substituida.")
    validate_connection(password, connect)
    store.put(COLLECTOR_REFERENCE, password)
    if store.get(COLLECTOR_REFERENCE) != password:
        raise ImportErrorSafe("A leitura de retorno do cofre nao confirmou a credencial. Pare antes de habilitar a integracao.")
    return {
        "modo": "credencial_collector_protegida",
        "protecao": "windows-dpapi-current-user",
        "conta_windows": "GALAXIA\\admin.pimentel",
        "referencia": COLLECTOR_REFERENCE,
        "conexao_validada": True,
        "leitura_dpapi_validada": True,
        "sincronizacao_habilitada": False,
    }


def main(argv=None):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        verify_windows_identity()
        if sys.stdin.isatty():
            raise ImportErrorSafe("Receba a senha pelo bloco PowerShell com Read-Host e pipe JSON UTF-8.")
        try:
            import psycopg
        except ImportError:
            raise ImportErrorSafe("Driver psycopg ausente neste Python. Use o ambiente de migracao.") from None
        store = JsonSecretStore()
        if store.contains(COLLECTOR_REFERENCE):
            raise ImportErrorSafe("A referencia do coletor ja existe. Nenhuma credencial foi substituida.")
        password = _read_password(from_stdin=True)
        try:
            result = configure(password, store=store, connect=psycopg.connect)
        finally:
            password = None
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except ImportErrorSafe as exc:
        print(str(exc), file=sys.stderr)
    except SecretStoreError:
        print("Falha ao acessar ou validar o cofre DPAPI. Nao habilite a integracao.", file=sys.stderr)
    except KeyboardInterrupt:
        print("Operacao interrompida. Confira a referencia no cofre antes de repetir.", file=sys.stderr)
    except Exception:
        print("Falha na preparacao da credencial. Detalhes foram omitidos por seguranca. Nao habilite a integracao.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
