"""Migrate environment.json secrets to the local DPAPI secret store."""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import re
import sys
import unicodedata


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.environment_loader import (  # noqa: E402
    CREDENTIAL_REFERENCE_KEY,
    SECRET_FIELD_NAMES,
    contains_credential_reference,
    is_credential_reference,
    load_environment_file,
    resolve_credential_references,
    save_environment_file,
)
from core.secret_store import JsonSecretStore, SecretStoreError  # noqa: E402


@dataclass(frozen=True)
class MigrationItem:
    path: tuple[str, ...]
    reference: str
    secret: str = field(repr=False)


class MigrationError(RuntimeError):
    """Migration failure whose message never includes secret values."""


def _reference_segment(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    segment = re.sub(r"[^a-z0-9._-]+", "-", ascii_value).strip("-._")
    if not segment:
        raise MigrationError("Um caminho de configuracao nao pode gerar referencia segura.")
    return segment


def reference_for_path(path: tuple[str, ...]) -> str:
    return "/".join(["environment", *(_reference_segment(part) for part in path)])


def display_path(path: tuple[str, ...]) -> str:
    return "$." + ".".join(path)


def build_migration_plan(payload: dict) -> list[MigrationItem]:
    items: list[MigrationItem] = []
    references: dict[str, tuple[str, ...]] = {}

    def walk(value: object, path: tuple[str, ...]) -> None:
        if isinstance(value, dict):
            for raw_key, child in value.items():
                key = str(raw_key)
                child_path = (*path, key)
                if key.strip().lower() in SECRET_FIELD_NAMES:
                    if is_credential_reference(child) or child in (None, ""):
                        continue
                    if not isinstance(child, str):
                        raise MigrationError(
                            f"Campo secreto com formato nao suportado em {display_path(child_path)}."
                        )
                    reference = reference_for_path(child_path)
                    previous = references.get(reference)
                    if previous is not None and previous != child_path:
                        raise MigrationError("Duas configuracoes geraram a mesma referencia de credencial.")
                    references[reference] = child_path
                    items.append(MigrationItem(child_path, reference, child))
                    continue
                walk(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, (*path, str(index)))

    walk(payload, ())
    return items


def _set_path(payload: dict, path: tuple[str, ...], value: object) -> None:
    current: object = payload
    for part in path[:-1]:
        if isinstance(current, dict):
            current = current[part]
        elif isinstance(current, list):
            current = current[int(part)]
        else:
            raise MigrationError("Estrutura do ambiente mudou durante a migracao.")
    if isinstance(current, dict):
        current[path[-1]] = value
    elif isinstance(current, list):
        current[int(path[-1])] = value
    else:
        raise MigrationError("Estrutura do ambiente mudou durante a migracao.")


def migrate_payload(payload: dict, *, secret_store) -> tuple[dict, list[MigrationItem]]:
    migrated = deepcopy(payload)
    items = build_migration_plan(payload)
    for item in items:
        secret_store.put(item.reference, item.secret)
        if secret_store.get(item.reference) != item.secret:
            raise MigrationError("Uma credencial nao passou na verificacao do cofre.")
        _set_path(
            migrated,
            item.path,
            {CREDENTIAL_REFERENCE_KEY: item.reference},
        )
    if items:
        resolved = resolve_credential_references(migrated, secret_store=secret_store)
        if resolved != payload:
            raise MigrationError("A verificacao integral da configuracao migrada falhou.")
    return migrated, items


def verify_payload(payload: dict, *, secret_store) -> int:
    if not contains_credential_reference(payload):
        raise MigrationError("O environment.json ainda nao possui referencias de credencial.")
    resolve_credential_references(payload, secret_store=secret_store)

    def count(value: object) -> int:
        if is_credential_reference(value):
            return 1
        if isinstance(value, dict):
            return sum(count(child) for child in value.values())
        if isinstance(value, list):
            return sum(count(child) for child in value)
        return 0

    return count(payload)


def rollback_payload(payload: dict, *, secret_store) -> tuple[dict, int]:
    references = verify_payload(payload, secret_store=secret_store)
    resolved = resolve_credential_references(payload, secret_store=secret_store)
    if not isinstance(resolved, dict):
        raise MigrationError("A configuracao recuperada possui formato invalido.")
    return resolved, references


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migra segredos do environment.json para o cofre DPAPI local."
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=PROJECT_ROOT / "environment.json",
        help="environment.json local do Sentinel.",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true", help="Aplica a migracao planejada.")
    action.add_argument("--verify", action="store_true", help="Verifica todas as referencias atuais.")
    action.add_argument(
        "--rollback",
        action="store_true",
        help="Restaura os valores no JSON sem apagar o cofre.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv or sys.argv[1:]))
    try:
        payload = load_environment_file(args.file, resolve_secrets=False)
        store = JsonSecretStore()
        if args.verify:
            references = verify_payload(payload, secret_store=store)
            print(f"OK: {references} referencia(s) validada(s), sem exibir valores.")
            return 0
        if args.rollback:
            restored, references = rollback_payload(payload, secret_store=store)
            save_environment_file(args.file, restored)
            print(
                f"ROLLBACK CONCLUIDO: {references} valor(es) restaurado(s) no JSON. "
                "O cofre foi preservado."
            )
            return 0

        plan = build_migration_plan(payload)
        if not plan:
            if contains_credential_reference(payload):
                print("Nenhum segredo em texto puro encontrado; use --verify.")
            else:
                print("Nenhum segredo preenchido foi encontrado para migracao.")
            return 0
        print(f"Plano seguro: {len(plan)} segredo(s) sera(ao) migrado(s):")
        for item in plan:
            print(f"  {display_path(item.path)} -> {item.reference}")
        if not args.apply:
            print("SIMULACAO: nenhum arquivo ou segredo foi alterado.")
            print("Use --apply somente depois de revisar este plano.")
            return 0

        migrated, items = migrate_payload(payload, secret_store=store)
        save_environment_file(args.file, migrated)
        references = verify_payload(
            load_environment_file(args.file, resolve_secrets=False),
            secret_store=store,
        )
        print(
            f"MIGRACAO CONCLUIDA: {len(items)} segredo(s) movido(s) e "
            f"{references} referencia(s) validada(s)."
        )
        return 0
    except (MigrationError, SecretStoreError, OSError, ValueError) as exc:
        print(f"ERRO SEGURO: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
