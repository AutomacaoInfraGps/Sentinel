"""Inventory sensitive JSON fields without exposing their values."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FILES = (
    "environment.json",
    "estrutura_regionais.json",
    "servidores.json",
)

SECRET_NAMES = {
    "api_key",
    "apikey",
    "access_token",
    "client_secret",
    "community",
    "pass",
    "passwd",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "senha",
    "token",
}
IDENTITY_NAMES = {
    "cpf",
    "data_nascimento",
    "login",
    "user",
    "username",
    "usuario",
}
DYNAMIC_CONTAINERS = {"fortigate", "regionais"}


def _normalized_name(value: object) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    return text.strip("_")


def classify_field(name: object) -> str | None:
    normalized = _normalized_name(name)
    if not normalized or normalized.endswith("_path"):
        return None
    if normalized in SECRET_NAMES or any(
        normalized.endswith(f"_{suffix}") for suffix in SECRET_NAMES
    ):
        return "secret"
    if normalized in IDENTITY_NAMES:
        return "identity"
    return None


def _display_key(parent_key: str | None, key: object) -> str:
    if _normalized_name(parent_key) in DYNAMIC_CONTAINERS:
        return "*"
    return str(key)


def inventory_payload(payload: object) -> Counter:
    findings: Counter = Counter()

    def walk(value: object, path: str, parent_key: str | None = None) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                display_key = _display_key(parent_key, key)
                child_path = f"{path}.{display_key}"
                classification = classify_field(key)
                if classification:
                    findings[(classification, child_path)] += 1
                walk(child, child_path, str(key))
        elif isinstance(value, list):
            for child in value:
                walk(child, f"{path}[*]", parent_key)

    walk(payload, "$")
    return findings


def inventory_file(path: Path) -> Counter:
    with path.open("r", encoding="utf-8-sig") as stream:
        return inventory_payload(json.load(stream))


def _safe_project_path(raw_path: str) -> Path:
    path = (PROJECT_ROOT / raw_path).resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError("Only JSON files inside the project can be inspected") from exc
    if path.suffix.lower() != ".json":
        raise ValueError("Only JSON files are accepted")
    return path


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List sensitive JSON field paths without showing values."
    )
    parser.add_argument("files", nargs="*", default=list(DEFAULT_FILES))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv or sys.argv[1:]))
    total_secrets = 0
    total_identities = 0
    errors = 0

    print("Sensitive field inventory (values are never displayed)")
    for raw_path in args.files:
        try:
            path = _safe_project_path(raw_path)
            if not path.exists():
                print(f"\n{path.name}: file not found")
                continue
            findings = inventory_file(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"\n{Path(raw_path).name}: unable to inspect ({type(exc).__name__})")
            errors += 1
            continue

        secret_count = sum(
            count for (classification, _), count in findings.items()
            if classification == "secret"
        )
        identity_count = sum(
            count for (classification, _), count in findings.items()
            if classification == "identity"
        )
        total_secrets += secret_count
        total_identities += identity_count

        print(
            f"\n{path.name}: {secret_count} secret field(s), "
            f"{identity_count} sensitive identity field(s)"
        )
        for (classification, field_path), count in sorted(findings.items()):
            print(f"  [{classification}] {field_path} ({count} occurrence(s))")

    print(
        f"\nTotal: {total_secrets} secret field(s), "
        f"{total_identities} sensitive identity field(s)"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
