"""Avalia atualizações FortiOS usando o catálogo do FortiManager."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo


BASE = "https://docs.fortinet.com"
INDEX = BASE + "/product/fortigate/"
_VERSION = re.compile(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)")
_MODEL = re.compile(r"\b(?:FG|FWF)-[A-Z0-9]+(?:-[A-Z0-9]+)*\b")


def version(value):
    match = _VERSION.search(str(value or ""))
    return tuple(map(int, match.groups())) if match else None


def model(value):
    text = str(value or "").strip().upper()
    text = re.sub(r"^FORTIGATE[-\s]*", "FG-", text)
    text = re.sub(r"^FORTIWIFI[-\s]*", "FWF-", text)
    return text if _MODEL.fullmatch(text) else None


def catalog_from_fortimanager(payload):
    """Converte /um/image/version/list em modelo -> releases GA."""
    try:
        data = payload["result"][0]["data"]
        if data.get("status") != "success":
            return None
        entries = data["version_list"]
    except (KeyError, IndexError, TypeError):
        return None

    catalog = {}
    for entry in entries if isinstance(entries, list) else []:
        identity = model(entry.get("platform")) if isinstance(entry, dict) else None
        if not identity:
            continue
        releases = {
            version(item.get("version"))
            for item in entry.get("versions", [])
            if isinstance(item, dict) and str(item.get("type") or "").upper() == "GA"
        }
        catalog[identity] = sorted(release for release in releases if release)
    return catalog or None


def _release_notes_url(release):
    value = ".".join(map(str, release))
    return f"{BASE}/document/fortigate/{value}/fortios-release-notes/760203/introduction-and-supported-models"


def assess(catalog, hardware, firmware, checked_at=None):
    checked = checked_at or datetime.now(ZoneInfo("America/Sao_Paulo"))
    if isinstance(checked, datetime):
        checked = checked.astimezone(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y - %H:%M")
    result = {
        "state": "unknown",
        "label": "Verificação indisponível",
        "url": INDEX,
        "message": "O FortiManager não confirmou a compatibilidade deste modelo e firmware.",
        "checked_at_display": str(checked or "Não disponível"),
        "stale": False,
        "update_kind": None,
    }
    installed, identity = version(firmware), model(hardware)
    if not catalog or not installed or not identity or identity not in catalog:
        return result

    family_releases = [release for release in catalog[identity]
                       if release[0] == installed[0]]
    if not family_releases:
        return result

    compatible = [release for release in family_releases if release > installed]
    if compatible:
        target = max(compatible)
        target_text = ".".join(map(str, target))
        result.update(
            state="update",
            label="Atualização disponível",
            url=_release_notes_url(target),
            message=f"Versão compatível disponível: {target_text}. Instalada: {firmware}.",
            available_version=target_text,
            update_kind="same_major",
        )
    else:
        result.update(
            state="current",
            label="Sem versão superior no FortiManager",
            message="Nenhuma versão superior da mesma família foi encontrada no FortiManager.",
        )
    return result


def format_firmware(value):
    """Padroniza apenas a apresentação do build, sem alterar o inventário."""
    return re.sub(r"\bbuild\s*(\d+)", r"Build \1", str(value or "N/A"), flags=re.IGNORECASE)
