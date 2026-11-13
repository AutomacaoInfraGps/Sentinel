"""Read-only preflight for the first operational PostgreSQL import."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import ipaddress
import json
import math
from pathlib import Path
import re
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MISSING = frozenset({"", "n/a", "unknown", "-", "none", "null"})


class AuditError(ValueError):
    """Only fixed messages are exposed; source values never enter diagnostics."""


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _timestamp_kind(value):
    if value is None or (isinstance(value, str) and value.strip().lower() in MISSING):
        return "missing"
    if not isinstance(value, str):
        return "invalid"
    try:
        if len(value.strip()) <= 10:
            return "invalid"
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return "naive" if moment.tzinfo is None else "aware"
    except ValueError:
        return "invalid"


def _expiry_kind(value):
    if value is None or (isinstance(value, str) and value.strip().lower() in MISSING):
        return "missing"
    if isinstance(value, bool):
        return "invalid"
    if isinstance(value, (int, float)) or (
        isinstance(value, str) and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value.strip())
    ):
        try:
            stamp = float(value)
            if not math.isfinite(stamp) or stamp < 0:
                return "invalid"
            if stamp == 0:
                return "missing"
            datetime.fromtimestamp(stamp, timezone.utc)
            return "instant"
        except (ValueError, OverflowError, OSError):
            return "invalid"
    if not isinstance(value, str):
        return "invalid"
    value = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            date.fromisoformat(value)
            return "date"
        if re.fullmatch(r"\d{2}/\d{2}/\d{4}", value):
            datetime.strptime(value, "%d/%m/%Y")
            return "date"
    except ValueError:
        return "invalid"
    kind = _timestamp_kind(value)
    return "instant" if kind == "aware" else kind


def _valid_text(value, maximum):
    return isinstance(value, str) and bool(value.strip()) and len(value.strip()) <= maximum


def _optional_text_valid(value, maximum):
    return value is None or (isinstance(value, str) and len(value.strip()) <= maximum)


def audit_payload(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("firewalls_por_regional"), dict):
        raise AuditError("Formato de cache de firewalls invalido.")
    regionals = payload["firewalls_por_regional"]
    errors, warnings, serials = Counter(), Counter(), Counter()
    expiry_types, timestamps = Counter(), Counter()
    firewall_count = license_count = 0
    for code, firewalls in regionals.items():
        if not _valid_text(code, 120) or code != code.strip():
            errors["codigo_regional_invalido"] += 1
        if not isinstance(firewalls, list):
            errors["lista_firewalls_invalida"] += 1
            continue
        for firewall in firewalls:
            firewall_count += 1
            if not isinstance(firewall, dict):
                errors["firewall_invalido"] += 1
                continue
            serial = _text(firewall.get("serial"))
            if not _valid_text(firewall.get("serial"), 120) or serial.lower() in MISSING:
                errors["serial_invalido"] += 1
            else:
                serials[serial.upper()] += 1
            if not _valid_text(firewall.get("nome") or firewall.get("hostname"), 240):
                errors["nome_firewall_invalido"] += 1
            for field in ("hostname", "firmware"):
                if not _optional_text_valid(firewall.get(field), 240):
                    errors["campo_firewall_invalido"] += 1
            if not _optional_text_valid(firewall.get("model") or firewall.get("modelo"), 240):
                errors["campo_firewall_invalido"] += 1
            address = firewall.get("ip")
            if address is not None and address != "":
                try:
                    if not isinstance(address, str):
                        raise ValueError
                    # An address with a subnet is not a single equipment address.
                    ipaddress.ip_address(address.strip())
                except ValueError:
                    errors["ip_firewall_invalido"] += 1
            timestamps[_timestamp_kind(firewall.get("ultima_verificacao") or firewall.get("atualizado_em"))] += 1
            licenses = firewall.get("licencas")
            if licenses is None or licenses == []:
                warnings["firewall_sem_detalhes_de_licencas"] += 1
                continue
            if not isinstance(licenses, list):
                errors["lista_licencas_invalida"] += 1
                continue
            for license_record in licenses:
                license_count += 1
                if not isinstance(license_record, dict):
                    errors["licenca_invalida"] += 1
                    continue
                if not _valid_text(license_record.get("nome") or license_record.get("tipo"), 240):
                    errors["nome_licenca_invalido"] += 1
                for field, size in (("tipo", 240), ("status", 120), ("origem", 120)):
                    if not _optional_text_valid(license_record.get(field), size):
                        errors["campo_licenca_invalido"] += 1
                days = license_record.get("dias_restantes")
                if days is not None and (isinstance(days, bool) or not isinstance(days, int) or not -(2**31) <= days < 2**31):
                    errors["dias_restantes_invalidos"] += 1
                for flag in ("notificacao_critica", "notificacao_expirada", "status_indisponivel"):
                    if license_record.get(flag) is not None and not isinstance(license_record[flag], bool):
                        errors["indicador_licenca_invalido"] += 1
                expiry_types[_expiry_kind(license_record.get("expiracao"))] += 1
    duplicates = sum(count - 1 for count in serials.values())
    if duplicates:
        errors["serial_duplicado"] = duplicates
    if not firewall_count:
        errors["cache_sem_firewalls"] += 1
    if expiry_types["invalid"]:
        errors["vencimento_invalido"] = expiry_types["invalid"]
    if timestamps["invalid"]:
        errors["data_coleta_invalida"] = timestamps["invalid"]
    if timestamps["missing"]:
        warnings["data_coleta_ausente"] = timestamps["missing"]
    if timestamps["naive"] or expiry_types["naive"]:
        warnings["datas_sem_fuso_exigem_configuracao_explicita"] = timestamps["naive"] + expiry_types["naive"]
    if expiry_types["missing"]:
        warnings["licenca_sem_vencimento_conhecido"] = expiry_types["missing"]
    return {
        "modo": "somente_conferencia_sem_banco",
        "regionais_no_cache": len(regionals),
        "firewalls": firewall_count,
        "licencas": license_count,
        "seriais_duplicados": duplicates,
        "vencimentos_com_instante": expiry_types["instant"],
        "vencimentos_apenas_data": expiry_types["date"],
        "vencimentos_sem_fuso": expiry_types["naive"],
        "vencimentos_ausentes": expiry_types["missing"],
        "coletas_sem_fuso": timestamps["naive"],
        "coletas_ausentes": timestamps["missing"],
        "erros": dict(sorted(errors.items())),
        "avisos": dict(sorted(warnings.items())),
        "estrutura_valida": not errors,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=PROJECT_ROOT / "output" / "dashboard_firewalls_cache.json")
    args = parser.parse_args(argv)
    try:
        with args.cache.open(encoding="utf-8-sig") as stream:
            payload = json.load(stream)
        result = audit_payload(payload)
    except (OSError, UnicodeError, json.JSONDecodeError):
        print("Nao foi possivel ler o cache JSON. Nenhum dado foi alterado.", file=sys.stderr)
        return 2
    except AuditError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if result["estrutura_valida"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
