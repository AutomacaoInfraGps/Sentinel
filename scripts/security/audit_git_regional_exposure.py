"""Compare regional passwords in Git history with the current encrypted vault."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.environment_loader import resolve_credential_references  # noqa: E402
from core.secret_store import JsonSecretStore, SecretStoreError  # noqa: E402


class AuditError(RuntimeError):
    """Audit failure whose message never includes credential values."""


@dataclass(frozen=True, order=True)
class ServerIdentity:
    regional: str
    server_id: str


def _run_git(*args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), *args],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AuditError("Nao foi possivel consultar o historico Git.")
    return result.stdout


def _server_credentials(payload: object) -> list[tuple[ServerIdentity, str]]:
    if not isinstance(payload, dict):
        return []

    credentials = []
    regionals = payload.get("regionais")
    if not isinstance(regionals, dict):
        return credentials

    for regional, regional_data in regionals.items():
        if not isinstance(regional_data, dict):
            continue
        servers = regional_data.get("servidores")
        if not isinstance(servers, list):
            continue
        for index, server in enumerate(servers):
            if not isinstance(server, dict):
                continue
            secret = server.get("senha")
            if not isinstance(secret, str) or not secret:
                continue
            identity = ServerIdentity(
                regional=str(regional),
                server_id=str(server.get("id") or f"index-{index}"),
            )
            credentials.append((identity, secret))
    return credentials


def collect_historical_credentials(
    *, git_ref: str, repository_path: str
) -> tuple[set[ServerIdentity], set[str], int]:
    commits = _run_git(
        "rev-list", git_ref, "--", repository_path
    ).decode("ascii", errors="strict").splitlines()

    identities: set[ServerIdentity] = set()
    secrets: set[str] = set()
    snapshots = 0
    for commit in commits:
        result = subprocess.run(
            [
                "git", "-C", str(PROJECT_ROOT), "show",
                f"{commit}:{repository_path}",
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            continue
        try:
            payload = json.loads(result.stdout.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuditError("Uma versao historica possui JSON invalido.") from exc
        snapshots += 1
        for identity, secret in _server_credentials(payload):
            identities.add(identity)
            secrets.add(secret)
    return identities, secrets, snapshots


def find_affected_current_servers(
    payload: object, compromised_secrets: set[str]
) -> list[ServerIdentity]:
    return sorted({
        identity
        for identity, secret in _server_credentials(payload)
        if secret in compromised_secrets
    })


def _load_current(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditError("A configuracao regional atual nao pode ser carregada.") from exc
    resolved = resolve_credential_references(
        payload, secret_store=JsonSecretStore()
    )
    if not isinstance(resolved, dict):
        raise AuditError("A configuracao regional atual possui formato invalido.")
    return resolved


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Identifica credenciais regionais atuais presentes no historico Git "
            "sem exibir os valores."
        )
    )
    parser.add_argument("--ref", default="origin/main")
    parser.add_argument(
        "--file", type=Path, default=PROJECT_ROOT / "estrutura_regionais.json"
    )
    parser.add_argument(
        "--repository-path", default="estrutura_regionais.json"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv or sys.argv[1:]))
    try:
        historical_servers, compromised_secrets, snapshots = (
            collect_historical_credentials(
                git_ref=args.ref,
                repository_path=args.repository_path,
            )
        )
        current = _load_current(args.file)
        affected = find_affected_current_servers(current, compromised_secrets)

        print("Auditoria segura do historico Git (valores nunca exibidos)")
        print(f"Versoes historicas analisadas: {snapshots}")
        print(f"Servidores presentes no historico: {len(historical_servers)}")
        print(f"Valores de senha distintos no historico: {len(compromised_secrets)}")
        print(f"Servidores atuais que ainda usam esses valores: {len(affected)}")
        for identity in affected:
            print(f"  {identity.regional} / {identity.server_id}")
        return 2 if affected else 0
    except (AuditError, SecretStoreError, ValueError) as exc:
        print(f"ERRO SEGURO: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
