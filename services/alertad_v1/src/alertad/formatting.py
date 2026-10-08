from __future__ import annotations

from datetime import timedelta, timezone
from html import escape

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.11 sempre possui zoneinfo
    ZoneInfo = None  # type: ignore[assignment]

from .contracts import DirectoryResolution, DirectoryResolutionStatus
from .models import ADGroupEvent, Action


def _brasilia_timezone():
    if ZoneInfo is not None:
        try:
            return ZoneInfo("America/Sao_Paulo")
        except Exception:
            pass
    return timezone(timedelta(hours=-3), name="BRT")


def resolved_member_label(
    event: ADGroupEvent,
    directory_resolution: DirectoryResolution | None = None,
) -> str:
    if (
        directory_resolution is not None
        and directory_resolution.status is DirectoryResolutionStatus.RESOLVED
        and directory_resolution.directory_object is not None
    ):
        directory_object = directory_resolution.directory_object
        if directory_object.domain_name:
            return f"{directory_object.domain_name}\\{directory_object.account_name}"
        return directory_object.account_name
    # Nunca substitui um MemberName válido por SID apenas porque uma tentativa
    # de enriquecimento falhou ou foi fornecida indevidamente pelo chamador.
    if event.member_name:
        return _common_name(event.member_name)
    if directory_resolution is not None:
        return event.member_sid
    return event.member


def _common_name(value: str) -> str:
    """Reduz um DN LDAP ao CN inicial sem revelar a hierarquia interna."""
    raw_value = value.strip()
    if not raw_value.casefold().startswith("cn="):
        return raw_value

    common_name: list[str] = []
    escaped = False
    for character in raw_value[3:]:
        if escaped:
            common_name.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ",":
            break
        else:
            common_name.append(character)
    if escaped:
        common_name.append("\\")
    return "".join(common_name).strip() or raw_value


def event_attentions(
    event: ADGroupEvent,
    directory_resolution: DirectoryResolution | None = None,
) -> list[str]:
    attentions: list[str] = []
    if not event.member_name:
        if directory_resolution is None:
            attentions.append("Nome do usuário não informado no evento; exibindo o SID.")
        elif directory_resolution.status is not DirectoryResolutionStatus.RESOLVED:
            attentions.append("Usuário não resolvido no diretório; exibindo o SID.")
    if not event.executor:
        attentions.append("Executor não informado no evento.")
    if not event.target_sid:
        attentions.append("SID do grupo não informado no evento.")
    return attentions


def format_alert(
    event: ADGroupEvent,
    directory_resolution: DirectoryResolution | None = None,
) -> str:
    action = "usuário adicionado" if event.action is Action.ADD else "usuário removido"
    timestamp = event.time_created_utc.astimezone(_brasilia_timezone())
    lines = [
        "SENTINEL | ALERTA DO ACTIVE DIRECTORY",
        "",
        "Movimentação detectada em um grupo monitorado.",
        "",
        f"Ação: {action}",
        f"Grupo: {event.target_user_name}",
        f"Usuário: {resolved_member_label(event, directory_resolution)}",
        f"Executor: {event.executor or 'Não informado'}",
        f"Origem: {event.source_computer}",
        f"Data/hora: {timestamp:%d/%m/%Y %H:%M:%S} (Brasília)",
    ]
    attentions = event_attentions(event, directory_resolution)
    if attentions:
        lines.extend(["", "Pontos de atenção:"])
        lines.extend(f"- {attention}" for attention in attentions)
    lines.extend(
        [
            "",
            "Se a alteração não for reconhecida, acione a equipe responsável.",
            "Mensagem automática do Sentinel | AlertAD.",
        ]
    )
    return "\n".join(lines)


def format_alert_html(message: str) -> str:
    """Apresenta os campos operacionais em tabela HTML aceita pelo Teams."""
    labels = ("Ação", "Grupo", "Usuário", "Executor", "Origem", "Data/hora")
    details: dict[str, str] = {}
    for raw_line in message.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        label, separator, value = line.partition(":")
        if separator and label in labels:
            normalized = value.strip()
            details[label] = _common_name(normalized) if label == "Usuário" else normalized

    if not details:
        return f"<div><strong>{escape(message.strip())}</strong></div>"

    rows = "".join(
        "<tr>"
        f'<td style="padding:6px 10px"><strong>{escape(label)}</strong></td>'
        f'<td style="padding:6px 10px">{escape(details.get(label, "Não informado"))}</td>'
        "</tr>"
        for label in labels
    )
    return (
        "<div>"
        "<p><strong>Sentinel | Alerta do Active Directory</strong></p>"
        "<p>Movimentação detectada em um grupo monitorado.</p>"
        '<table border="1" cellpadding="0" cellspacing="0" '
        'style="border-collapse:collapse">'
        f"{rows}</table>"
        "<p>Se a alteração não for reconhecida, acione a equipe responsável.</p>"
        "<p><em>Mensagem automática do Sentinel | AlertAD.</em></p>"
        "</div>"
    )

