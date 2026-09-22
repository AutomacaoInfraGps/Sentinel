"""Escopo regional do Sentinel derivado dos grupos de segurança do AD."""

import difflib
import json
import os
import re
import tempfile
import unicodedata
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from threading import Lock

from config import PROJECT_ROOT


CORPORATE_GROUP = "GGS_SUPORTE_CORPORATIVO"
ADMINISTRATIVE_OU_DN = "OU=Usuarios Administrativos,OU=Galaxia,DC=Galaxia,DC=local"
ADMINISTRATIVE_OU_MARKER = "SENTINEL_ADMINISTRATIVE_OU"
FULL_VIEW_GROUPS = {
    "ACCOUNT OPERATORS",
    "REMOTE DESKTOP USERS",
    "DOMAIN ADMINS",
    "ENTERPRISE ADMINS",
    "SCHEMA ADMINS",
    "ADMINISTRATORS",
    ADMINISTRATIVE_OU_MARKER,
}
ACCESS_ADMIN_GROUPS = {
    "DOMAIN ADMINS",
    "ENTERPRISE ADMINS",
    "SCHEMA ADMINS",
    "ADMINISTRATORS",
}
OPERATOR_GROUPS = ACCESS_ADMIN_GROUPS | {ADMINISTRATIVE_OU_MARKER}
DYNAMIC_MAPPINGS_FILE = PROJECT_ROOT / "output" / "regional_access_mappings.json"
DISCOVERED_GROUPS_FILE = PROJECT_ROOT / "output" / "regional_access_discovered.json"
_files_lock = Lock()

GROUP_REGIONALS = {
    "GGS_SUPORTE_RS": {"REG_TLSV_POA", "REG_LEOPOLDO_B2", "REG_CAXIAS", "REG_SAO_LEOPOLDO", "REG_RUDDER", "REG_SULZER"},
    "GGS_SUPORTE_ARARAS": {"REG_ARARAS"},
    "GGS_SUPORTE_LOGHIS": {"REG_ARARAS", "REG_LOGHIS"},
    "GGS_SUPORTE_ABC": {"REG_PRAIA_GRANDE", "REG_ABC"},
    "GGS_SUPORTE_CAMPINAS": {"REG_CAMPINAS", "REG_CAMPINAS_02"},
    "GGS_SUPORTE_SJC": {"REG_SJC"},
    "GGS_SUPORTE_SOROCABA": {"REG_SOROCABA"},
    "GGS_SUPORTE_T&T": {"REG_TRADETALENTOS"},
    "GGS_SUPORTE_CEARA": {"REG_CEARA", "REG_CEARA_2"},
    "GGS_SUPORTE_RN": {"REG_RIO_GRANDE_DO_NORTE"},
    "GGS_SUPORTE_NUTRICAR": {"REG_NUTRICAR"},
    "GGS_SUPORTE_ORMEC": {"REG_ORMEC_PARA"},
    "GGS_SUPORTE_GR_SANTANA_DE_PARNAIBA": {"REG_GRSASP"},
    "GGS_SUPORTE_BH": {"REG_REGIONAL BELO HORIZONTE"},
    "GGS_SUPORTE_MOTUS": {"REG_MOTUS"},
    "GGS_SUPORTE_PERNAMBUCO": {"REG_PERNAMBUCO"},
    "GGS_SUPORTE_BRASILIA": {"REG_GLOBAL_SEGURANÇA"},
    "GGS_SUPORTE_ALAGOAS": {"REG_ALAGOAS", "REG_CONTROL_MACEIO"},
    "GGS_SUPORTE_PIAUI": {"REG_PIAUÍ"},
    "GGS_SUPORTE_MARANHAO": {"REG_PIAUÍ", "REG_MARANHAO"},
    "GGS_SUPORTE_GR_LC": {"REG_GRSA_MACAE"},
    "GGS_SUPORTE_RJ": {"REG_GRSA_MACAE", "REG_RIO_DE_JANEIRO", "REG_MACAE"},
    "GGS_SUPORTE_ES": {"REG_ESPIRITO_SANTO"},
    "GGS_SUPORTE_BAHIA": {"REG_BAHIA"},
    "GGS_SUPORTE_AMAZONAS": {"REG_AMAZONAS"},
    "GGS_SUPORTE_GOIAS": {"REG_GOIAS"},
    "GGS_SUPORTE_UBERLANDIA": {"REG_UBERLANDIA"},
    "GGS_SUPORTE_PARA": {"REG_PARA"},
    "GGS_SUPORTE_PARANA": {"REG_PARANA"},
    "GGS_SUPORTE_RHMED": {"REG_RHMED"},
    "GGS_SUPORTE_MACAE": {"REG_MACAE"},
}


def normalize_group_name(value):
    text = str(value or "").strip()
    match = re.search(r"(?:^|,)CN=((?:\\.|[^,])*)", text, flags=re.IGNORECASE)
    if match:
        text = match.group(1).replace("\\,", ",")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return text.strip().upper()


def _normalize_dn(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").upper()
    return re.sub(r"\s*([,=])\s*", r"\1", text.strip())


def is_administrative_ou_dn(user_dn, organizational_unit=ADMINISTRATIVE_OU_DN):
    normalized_dn = _normalize_dn(user_dn)
    normalized_ou = _normalize_dn(organizational_unit)
    return bool(normalized_dn and normalized_ou and normalized_ou in normalized_dn)


def effective_user_groups(groups, user_dn=None):
    effective = [
        str(group).strip()
        for group in (groups or [])
        if str(group).strip()
    ]
    if is_administrative_ou_dn(user_dn):
        effective.append(ADMINISTRATIVE_OU_MARKER)
    return tuple(dict.fromkeys(effective))


def normalize_regional_code(value):
    text = str(value or "").strip().upper().replace("&", "")
    text = re.sub(r"[\s-]+", "_", text)
    return re.sub(r"_+", "_", text)


def _load_json(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(payload, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}-", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def dynamic_group_mapping(path=None):
    payload = _load_json(path or DYNAMIC_MAPPINGS_FILE)
    return {
        normalize_group_name(group): {
            normalize_regional_code(code) for code in (codes or [])
        }
        for group, codes in (payload.get("mappings") or {}).items()
        if normalize_group_name(group).startswith("GGS_SUPORTE_")
    }


def normalized_group_mapping(dynamic_path=None):
    mapping = {
        normalize_group_name(group): {normalize_regional_code(code) for code in codes}
        for group, codes in GROUP_REGIONALS.items()
    }
    for group, codes in dynamic_group_mapping(dynamic_path).items():
        mapping.setdefault(group, set()).update(codes)
    return mapping


def is_corporate(groups):
    return normalize_group_name(CORPORATE_GROUP) in {
        normalize_group_name(group) for group in (groups or [])
    }


def has_full_view(groups):
    group_names = {normalize_group_name(group) for group in (groups or [])}
    return bool(group_names.intersection({normalize_group_name(group) for group in FULL_VIEW_GROUPS}))


def can_manage_regional_access(groups):
    group_names = {normalize_group_name(group) for group in (groups or [])}
    return (
        normalize_group_name(CORPORATE_GROUP) in group_names
        or bool(group_names.intersection({normalize_group_name(group) for group in ACCESS_ADMIN_GROUPS}))
    )


def can_operate_sentinel(groups):
    group_names = {normalize_group_name(group) for group in (groups or [])}
    return (
        normalize_group_name(CORPORATE_GROUP) in group_names
        or bool(group_names.intersection({normalize_group_name(group) for group in OPERATOR_GROUPS}))
    )


def has_sentinel_login_access(username, groups):
    group_names = {normalize_group_name(group) for group in (groups or [])}
    if has_full_view(group_names) or normalize_group_name(CORPORATE_GROUP) in group_names:
        return True
    return any(group.startswith("GGS_SUPORTE_") for group in group_names)


def observe_support_groups(groups, path=None):
    known = set(normalized_group_mapping()) | {normalize_group_name(CORPORATE_GROUP)}
    observed = {
        normalize_group_name(group) for group in (groups or [])
        if normalize_group_name(group).startswith("GGS_SUPORTE_")
        and normalize_group_name(group) not in known
    }
    if not observed:
        return []
    state_path = Path(path or DISCOVERED_GROUPS_FILE)
    with _files_lock:
        state = _load_json(state_path)
        discovered = state.setdefault("groups", {})
        now = datetime.now().isoformat()
        for group in observed:
            record = discovered.setdefault(group, {"first_seen": now})
            record["last_seen"] = now
            record.setdefault("status", "pending")
        _write_json(state, state_path)
    return sorted(observed)


def _similarity_token(value):
    token = normalize_regional_code(value)
    for prefix in ("GGS_SUPORTE_", "REG_CONTROL_", "REG_REGIONAL_", "REG_"):
        if token.startswith(prefix):
            token = token[len(prefix):]
    return token


def suggest_regional(group, available_regionals):
    source = _similarity_token(group)
    candidates = []
    for regional in available_regionals or []:
        score = difflib.SequenceMatcher(None, source, _similarity_token(regional)).ratio()
        candidates.append((score, str(regional)))
    score, regional = max(candidates, default=(0.0, None))
    return regional, round(score, 3)


def pending_group_suggestions(available_regionals, path=None):
    state = _load_json(path or DISCOVERED_GROUPS_FILE)
    known = set(normalized_group_mapping()) | {normalize_group_name(CORPORATE_GROUP)}
    suggestions = []
    for group, record in sorted((state.get("groups") or {}).items()):
        group_name = normalize_group_name(group)
        if group_name in known or record.get("status") != "pending":
            continue
        regional, score = suggest_regional(group_name, available_regionals)
        suggestions.append({
            "group": group_name,
            "suggested_regional": regional,
            "score": score,
            "first_seen": record.get("first_seen"),
            "last_seen": record.get("last_seen"),
        })
    return suggestions


def approve_group_mapping(group, regional, mappings_path=None, discovered_path=None):
    group_name = normalize_group_name(group)
    regional_code = normalize_regional_code(regional)
    if not group_name.startswith("GGS_SUPORTE_") or group_name == normalize_group_name(CORPORATE_GROUP):
        raise ValueError("Grupo de suporte inválido.")
    if not regional_code:
        raise ValueError("Regional inválida.")
    mapping_path = Path(mappings_path or DYNAMIC_MAPPINGS_FILE)
    discovery_path = Path(discovered_path or DISCOVERED_GROUPS_FILE)
    with _files_lock:
        mappings = _load_json(mapping_path)
        current = mappings.setdefault("mappings", {}).setdefault(group_name, [])
        if regional_code not in current:
            current.append(regional_code)
            current.sort()
        mappings["updated_at"] = datetime.now().isoformat()
        _write_json(mappings, mapping_path)

        discovered = _load_json(discovery_path)
        record = discovered.setdefault("groups", {}).setdefault(group_name, {})
        record.update({"status": "approved", "approved_regional": regional_code, "approved_at": datetime.now().isoformat()})
        _write_json(discovered, discovery_path)
    return {"group": group_name, "regional": regional_code}


def access_scope(groups, available_regionals=None, dynamic_path=None):
    group_names = {normalize_group_name(group) for group in (groups or [])}
    available = {
        normalize_regional_code(code): str(code)
        for code in (available_regionals or [])
        if str(code or "").strip()
    }
    corporate = normalize_group_name(CORPORATE_GROUP) in group_names
    full_view = bool(group_names.intersection({normalize_group_name(group) for group in FULL_VIEW_GROUPS}))
    access_admin = can_manage_regional_access(group_names)
    if corporate or full_view:
        allowed = set(available) if available else {code for codes in normalized_group_mapping().values() for code in codes}
    else:
        allowed = set()
        mapping = normalized_group_mapping(dynamic_path)
        for group in group_names:
            allowed.update(mapping.get(group, set()))
    if available:
        allowed.intersection_update(available)
    return {
        "corporate": corporate,
        "full_view": full_view,
        "access_admin": access_admin,
        "groups": group_names,
        "allowed": allowed,
    }


def can_access_regional(groups, regional_code, available_regionals=None):
    return normalize_regional_code(regional_code) in access_scope(groups, available_regionals)["allowed"]


def filter_records(records, groups, regional_field="regional", available_regionals=None):
    scope = access_scope(groups, available_regionals)
    if scope["corporate"] or scope["full_view"]:
        return [dict(record) for record in (records or [])]
    return [
        dict(record) for record in (records or [])
        if normalize_regional_code(record.get(regional_field)) in scope["allowed"]
    ]


def filter_operational_payload(payload, groups, available_regionals=None):
    filtered = deepcopy(payload or {})
    scope = access_scope(groups, available_regionals)
    allowed = scope["allowed"]
    if not (scope["corporate"] or scope["full_view"]):
        for group_data in (filtered.get("groups") or {}).values():
            group_data["records"] = [
                record for record in (group_data.get("records") or [])
                if normalize_regional_code(record.get("regional")) in allowed
            ]
    filtered["regionals"] = [
        regional for regional in (filtered.get("regionals") or [])
        if normalize_regional_code(regional.get("codigo")) in allowed
    ]
    return filtered


def filter_map_payload(payload, groups, available_regionals=None):
    filtered = deepcopy(payload or {})
    scope = access_scope(groups, available_regionals)
    allowed = scope["allowed"]
    filtered["regionais"] = [
        regional for regional in (filtered.get("regionais") or [])
        if normalize_regional_code(regional.get("codigo")) in allowed
    ]
    if not (scope["corporate"] or scope["full_view"]):
        filtered["unmapped"] = {
            key: [] for key in (filtered.get("unmapped") or {})
        }
    resumo = {}
    for regional in filtered["regionais"]:
        for key, value in (regional.get("totais") or {}).items():
            if isinstance(value, (int, float)):
                resumo[key] = resumo.get(key, 0) + value
    resumo["total_regionais"] = len(filtered["regionais"])
    filtered["resumo"] = resumo
    return filtered
