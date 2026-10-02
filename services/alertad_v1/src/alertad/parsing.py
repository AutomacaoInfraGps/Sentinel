from __future__ import annotations

from datetime import datetime, timezone
from xml.etree import ElementTree

from .models import ADGroupEvent, EVENT_DEFINITIONS


MAX_EVENT_XML_CHARACTERS = 1_000_000
SECURITY_PROVIDER = "Microsoft-Windows-Security-Auditing"

class EventParseError(ValueError):
    """XML ausente, inválido ou sem campos obrigatórios."""


class UnsupportedEventError(EventParseError):
    """Event ID fora do contrato atual."""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(parent: ElementTree.Element, name: str) -> ElementTree.Element | None:
    return next((item for item in parent if _local_name(item.tag) == name), None)


def _text(element: ElementTree.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value if value and value != "-" else None


def _required(value: str | None, field_name: str) -> str:
    if value is None:
        raise EventParseError(f"Campo obrigatório ausente: {field_name}")
    return value


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EventParseError("System/TimeCreated/@SystemTime inválido") from exc
    if parsed.tzinfo is None:
        raise EventParseError("System/TimeCreated/@SystemTime deve possuir fuso horário")
    return parsed.astimezone(timezone.utc)


def parse_windows_event(xml_text: str) -> ADGroupEvent:
    if not isinstance(xml_text, str) or not xml_text.strip():
        raise EventParseError("XML do evento não pode ser vazio")
    if len(xml_text) > MAX_EVENT_XML_CHARACTERS:
        raise EventParseError("XML do evento excede o tamanho máximo permitido")
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise EventParseError("XML do evento inválido") from exc

    if _local_name(root.tag) != "Event":
        raise EventParseError("Elemento raiz deve ser Event")

    system = _child(root, "System")
    event_data = _child(root, "EventData")
    if system is None or event_data is None:
        raise EventParseError("XML deve conter System e EventData")

    provider = _child(system, "Provider")
    provider_name = provider.get("Name") if provider is not None else None
    if provider_name != SECURITY_PROVIDER:
        raise EventParseError("System/Provider não corresponde à auditoria de segurança")

    event_id_text = _required(_text(_child(system, "EventID")), "System/EventID")
    try:
        event_id = int(event_id_text)
    except ValueError as exc:
        raise EventParseError("System/EventID deve ser numérico") from exc

    definition = EVENT_DEFINITIONS.get(event_id)
    if definition is None:
        raise UnsupportedEventError(f"Event ID não suportado: {event_id}")

    record_id_text = _required(
        _text(_child(system, "EventRecordID")),
        "System/EventRecordID",
    )
    try:
        event_record_id = int(record_id_text)
    except ValueError as exc:
        raise EventParseError("System/EventRecordID deve ser numérico") from exc
    if event_record_id < 1:
        raise EventParseError("System/EventRecordID deve ser positivo")

    time_created = _child(system, "TimeCreated")
    timestamp_text = time_created.get("SystemTime") if time_created is not None else None
    timestamp = _parse_timestamp(
        _required(timestamp_text, "System/TimeCreated/@SystemTime")
    )

    values: dict[str, str | None] = {}
    for item in event_data:
        if _local_name(item.tag) == "Data" and item.get("Name"):
            name = item.get("Name", "")
            if name in values:
                raise EventParseError(f"Campo EventData duplicado: {name}")
            values[name] = _text(item)

    return ADGroupEvent(
        event_id=event_id,
        action=definition.action,
        group_scope=definition.group_scope,
        time_created_utc=timestamp,
        event_record_id=event_record_id,
        channel=_required(_text(_child(system, "Channel")), "System/Channel"),
        source_computer=_required(_text(_child(system, "Computer")), "System/Computer"),
        member_name=values.get("MemberName"),
        member_sid=_required(values.get("MemberSid"), "EventData/MemberSid"),
        target_user_name=_required(
            values.get("TargetUserName"),
            "EventData/TargetUserName",
        ),
        target_domain_name=values.get("TargetDomainName"),
        target_sid=values.get("TargetSid"),
        subject_user_sid=values.get("SubjectUserSid"),
        subject_user_name=values.get("SubjectUserName"),
        subject_domain_name=values.get("SubjectDomainName"),
        subject_logon_id=values.get("SubjectLogonId"),
        raw_xml=xml_text,
        time_created_raw=timestamp_text,
    )

