from __future__ import annotations

from datetime import timedelta, timezone

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
        return event.member_name
    if directory_resolution is not None:
        return event.member_sid
    return event.member


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
        "ALERTA CRÍTICO — GRUPO DO ACTIVE DIRECTORY",
        "",
        f"Ação: {action}",
        f"Grupo: {event.target_user_name}",
        f"Usuário: {resolved_member_label(event, directory_resolution)}",
        f"Executor: {event.executor or 'Não informado'}",
        f"Origem: {event.source_computer}",
        f"Data/hora: {timestamp:%d/%m/%Y %H:%M:%S} (Brasília)",
        f"Evento: {event.event_id}",
        f"Registro: {event.event_record_id}",
        f"Alert ID: {event.event_key[:12]}",
    ]
    attentions = event_attentions(event, directory_resolution)
    if attentions:
        lines.extend(["", "Pontos de atenção:"])
        lines.extend(f"- {attention}" for attention in attentions)
    return "\n".join(lines)

