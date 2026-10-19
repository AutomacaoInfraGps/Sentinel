"""Transfer a Sentinel vault between Windows users on the same machine."""

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.secret_store import (  # noqa: E402
    DEFAULT_STORE_PATH,
    DpapiLocalMachineProtector,
    JsonSecretStore,
    SecretStoreError,
)


DEFAULT_TRANSFER_PATH = DEFAULT_STORE_PATH.parent / "sentinel-secrets.transfer.json"


def _references(store: JsonSecretStore) -> list[str]:
    return list(store._load_unlocked()["entries"])


def export_transfer(source_path: Path, transfer_path: Path) -> int:
    if os.name != "nt":
        raise SecretStoreError("A transferencia DPAPI esta disponivel somente no Windows.")
    if source_path.resolve() == transfer_path.resolve():
        raise SecretStoreError("O arquivo de transferencia deve ser diferente do cofre.")

    source = JsonSecretStore(source_path)
    references = _references(source)
    if not references:
        raise SecretStoreError("O cofre de origem nao possui credenciais.")

    secrets = source.get_many(references)
    transfer_path.unlink(missing_ok=True)
    transfer = JsonSecretStore(
        transfer_path,
        protector=DpapiLocalMachineProtector(),
    )
    transfer.put_many(secrets)
    if transfer.get_many(references) != secrets:
        raise SecretStoreError("A transferencia nao passou na verificacao.")
    print(
        f"TRANSFERENCIA CRIADA: {len(references)} credencial(is) protegida(s), "
        "sem exibir valores."
    )
    return len(references)


def import_transfer(
    destination_path: Path,
    transfer_path: Path,
    *,
    keep_transfer: bool = False,
) -> int:
    if not transfer_path.is_file():
        raise SecretStoreError("O arquivo de transferencia nao foi encontrado.")

    transfer = JsonSecretStore(
        transfer_path,
        protector=DpapiLocalMachineProtector(),
    )
    references = _references(transfer)
    if not references:
        raise SecretStoreError("A transferencia nao possui credenciais.")
    secrets = transfer.get_many(references)

    backup_path = destination_path.with_name(
        f"{destination_path.stem}.before-rekey-{datetime.now():%Y%m%d-%H%M%S}.json"
    )
    if destination_path.is_file():
        shutil.copy2(destination_path, backup_path)

    destination = JsonSecretStore(destination_path)
    destination.put_many(secrets)
    if destination.get_many(references) != secrets:
        raise SecretStoreError("O cofre recriptografado nao passou na verificacao.")

    if not keep_transfer:
        transfer_path.unlink(missing_ok=True)
        Path(f"{transfer_path}.lock").unlink(missing_ok=True)

    print(
        f"IMPORTACAO CONCLUIDA: {len(references)} credencial(is) "
        "recriptografada(s) para o usuario Windows atual."
    )
    if backup_path.is_file():
        print(f"Backup protegido preservado em: {backup_path}")
    return len(references)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recriptografa o cofre Sentinel entre usuarios da mesma maquina."
    )
    parser.add_argument("action", choices=("export", "import"))
    parser.add_argument("--vault", type=Path, default=DEFAULT_STORE_PATH)
    parser.add_argument("--transfer", type=Path, default=DEFAULT_TRANSFER_PATH)
    parser.add_argument("--keep-transfer", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv or sys.argv[1:]))
    try:
        if args.action == "export":
            export_transfer(args.vault, args.transfer)
        else:
            import_transfer(
                args.vault,
                args.transfer,
                keep_transfer=args.keep_transfer,
            )
        return 0
    except (OSError, SecretStoreError, ValueError) as exc:
        print(f"ERRO SEGURO: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
