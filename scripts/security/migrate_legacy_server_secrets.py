"""Migrate passwords from the legacy servidores.json to the DPAPI vault."""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import tempfile
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.environment_loader import (  # noqa: E402
    CREDENTIAL_REFERENCE_KEY,
    is_credential_reference,
    resolve_credential_references,
)
from core.secret_store import JsonSecretStore, SecretStoreError  # noqa: E402
from gerenciar_servidores import (  # noqa: E402
    GerenciadorServidores,
    LEGACY_CREDENTIAL_STORAGE,
)


@dataclass(frozen=True)
class MigrationItem:
    index: int
    server_id: str
    reference: str
    secret: str = field(repr=False)


class MigrationError(RuntimeError):
    """Migration failure whose message never includes credential values."""


def load_raw(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError("O servidores.json nao pode ser carregado.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("servidores"), list):
        raise MigrationError("O servidores.json possui formato invalido.")
    return payload


def save_raw(path: Path, payload: dict) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".servidores-", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def build_plan(payload: dict) -> list[MigrationItem]:
    helper = GerenciadorServidores.__new__(GerenciadorServidores)
    items = []
    references = set()
    for index, servidor in enumerate(payload.get("servidores", [])):
        if not isinstance(servidor, dict):
            continue
        secret = servidor.get("senha")
        if is_credential_reference(secret) or secret in (None, ""):
            continue
        if not isinstance(secret, str):
            raise MigrationError("Uma senha legada possui formato nao suportado.")
        reference = GerenciadorServidores._server_reference(helper, servidor, index)
        if reference in references:
            raise MigrationError("Dois servidores geraram a mesma referencia de credencial.")
        references.add(reference)
        items.append(MigrationItem(
            index=index,
            server_id=str(servidor.get("id") or f"index-{index}"),
            reference=reference,
            secret=secret,
        ))
    return items


def migrate_payload(payload: dict, *, secret_store) -> tuple[dict, list[MigrationItem]]:
    migrated = deepcopy(payload)
    items = build_plan(payload)
    secrets = {item.reference: item.secret for item in items}
    if secrets and hasattr(secret_store, "put_many"):
        secret_store.put_many(secrets)
    else:
        for reference, secret in secrets.items():
            secret_store.put(reference, secret)
    for item in items:
        if secret_store.get(item.reference) != item.secret:
            raise MigrationError("Uma credencial nao passou na verificacao do cofre.")
        migrated["servidores"][item.index]["senha"] = {
            CREDENTIAL_REFERENCE_KEY: item.reference
        }
    migrated.setdefault("configuracao", {})["credential_storage"] = (
        LEGACY_CREDENTIAL_STORAGE
    )
    resolved = resolve_credential_references(migrated, secret_store=secret_store)
    expected = deepcopy(payload)
    expected.setdefault("configuracao", {})["credential_storage"] = (
        LEGACY_CREDENTIAL_STORAGE
    )
    if resolved != expected:
        raise MigrationError("A verificacao integral dos servidores legados falhou.")
    return migrated, items


def verify_payload(payload: dict, *, secret_store) -> int:
    if payload.get("configuracao", {}).get("credential_storage") != LEGACY_CREDENTIAL_STORAGE:
        raise MigrationError("O armazenamento seguro legado ainda nao esta habilitado.")
    references = []
    plaintext = 0
    for servidor in payload.get("servidores", []):
        value = servidor.get("senha") if isinstance(servidor, dict) else None
        if is_credential_reference(value):
            references.append(value[CREDENTIAL_REFERENCE_KEY])
        elif value not in (None, ""):
            plaintext += 1
    if plaintext:
        raise MigrationError("Ainda existem senhas em texto puro no servidores.json.")
    if not references:
        raise MigrationError("Nenhuma referencia legada foi encontrada.")
    for reference in references:
        secret_store.get(reference)
    return len(references)


def rollback_payload(payload: dict, *, secret_store) -> tuple[dict, int]:
    count = verify_payload(payload, secret_store=secret_store)
    restored = resolve_credential_references(payload, secret_store=secret_store)
    restored.get("configuracao", {}).pop("credential_storage", None)
    return restored, count


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migra senhas do servidores.json para o cofre DPAPI local."
    )
    parser.add_argument(
        "--file", type=Path, default=PROJECT_ROOT / "servidores.json"
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true")
    action.add_argument("--verify", action="store_true")
    action.add_argument("--rollback", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv or sys.argv[1:]))
    try:
        payload = load_raw(args.file)
        store = JsonSecretStore()
        if args.verify:
            count = verify_payload(payload, secret_store=store)
            print(f"OK: {count} referencia(s) legada(s) validada(s), sem exibir valores.")
            return 0
        if args.rollback:
            restored, count = rollback_payload(payload, secret_store=store)
            save_raw(args.file, restored)
            print(
                f"ROLLBACK CONCLUIDO: {count} senha(s) restaurada(s) no JSON. "
                "O cofre foi preservado."
            )
            return 0

        plan = build_plan(payload)
        if not plan:
            if payload.get("configuracao", {}).get("credential_storage") == LEGACY_CREDENTIAL_STORAGE:
                print("Nenhuma senha em texto puro encontrada; use --verify.")
            else:
                print("Nenhuma senha legada preenchida foi encontrada para migracao.")
            return 0
        print(f"Plano seguro: {len(plan)} senha(s) legada(s) sera(ao) migrada(s).")
        for item in plan:
            print(f"  {item.server_id} -> {item.reference}")
        if not args.apply:
            print("SIMULACAO: nenhum arquivo ou segredo foi alterado.")
            print("Use --apply somente depois de revisar este plano.")
            return 0

        migrated, items = migrate_payload(payload, secret_store=store)
        save_raw(args.file, migrated)
        count = verify_payload(load_raw(args.file), secret_store=store)
        print(
            f"MIGRACAO CONCLUIDA: {len(items)} senha(s) movida(s) e "
            f"{count} referencia(s) validada(s)."
        )
        return 0
    except (MigrationError, SecretStoreError, OSError, ValueError) as exc:
        print(f"ERRO SEGURO: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
