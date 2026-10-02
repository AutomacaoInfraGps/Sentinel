from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass
from typing import Callable, Protocol
from xml.etree import ElementTree

from .contracts import (
    MAX_EVENT_BATCH_SIZE,
    CollectedEvent,
    EventBatch,
    EventCheckpoint,
)
from .models import EVENT_DEFINITIONS


LOGGER = logging.getLogger(__name__)
CURSOR_VERSION = 2
DEFAULT_OVERLAP_SIZE = 10
MAX_OVERLAP_SIZE = 500


class EventLogReadError(RuntimeError):
    """Falha de leitura local sem incluir XML ou bookmark na mensagem."""

    def __init__(self, reason_code: str, *, windows_error: int | None = None) -> None:
        self.reason_code = reason_code
        self.windows_error = windows_error
        suffix = f"; código Windows={windows_error}" if windows_error is not None else ""
        super().__init__(f"Falha na leitura local do Windows Event Log: {reason_code}{suffix}")


class InvalidBookmarkError(EventLogReadError):
    """O Windows não reconhece mais o bookmark no log consultado."""


class InvalidCheckpointError(ValueError):
    """O envelope opaco não pertence a esta fonte ou está corrompido."""


@dataclass(frozen=True)
class EventLogRecord:
    xml: str
    bookmark: str

    def __post_init__(self) -> None:
        if not self.xml.strip():
            raise ValueError("Registro do Event Log não pode possuir XML vazio")
        if not self.bookmark.strip():
            raise ValueError("Registro do Event Log não pode possuir bookmark vazio")


@dataclass(frozen=True)
class EventLogPage:
    records: tuple[EventLogRecord, ...]
    has_more: bool


class LocalEventLogBackend(Protocol):
    """Porta local para a Windows Event Log API, substituível por fake."""

    def log_identity(self, channel: str) -> str: ...

    def latest_bookmark(self, channel: str, xpath_query: str) -> str | None: ...

    def read_events(
        self,
        channel: str,
        xpath_query: str,
        *,
        after_bookmark: str | None,
        overlap: int,
        limit: int,
    ) -> EventLogPage: ...


@dataclass(frozen=True)
class _Cursor:
    channel: str
    log_identity: str
    anchor_bookmark: str | None
    resume_bookmark: str | None
    in_progress: bool
    replaying_overlap: bool
    overlap_ready: bool
    lower_bound_bookmark: str | None
    recent_bookmarks: tuple[str, ...]

    def encode(self) -> str:
        return json.dumps(
            {
                "version": CURSOR_VERSION,
                "channel": self.channel,
                "log_identity": self.log_identity,
                "anchor_bookmark": self.anchor_bookmark,
                "resume_bookmark": self.resume_bookmark,
                "in_progress": self.in_progress,
                "replaying_overlap": self.replaying_overlap,
                "overlap_ready": self.overlap_ready,
                "lower_bound_bookmark": self.lower_bound_bookmark,
                "recent_bookmarks": list(self.recent_bookmarks),
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def decode(
        cls,
        value: str,
        *,
        channel: str,
        current_log_identity: str,
        legacy: bool,
    ) -> "_Cursor":
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            if legacy and value.lstrip().startswith("<Bookmark"):
                return cls(
                    channel,
                    current_log_identity,
                    value,
                    None,
                    False,
                    False,
                    True,
                    value,
                    (value,),
                )
            raise InvalidCheckpointError("Checkpoint possui envelope opaco inválido")

        if not isinstance(payload, dict) or payload.get("version") not in {1, CURSOR_VERSION}:
            raise InvalidCheckpointError("Versão do envelope de checkpoint não suportada")
        if payload.get("channel") != channel:
            raise InvalidCheckpointError("Checkpoint pertence a outro canal")

        log_identity = payload.get("log_identity")
        anchor = payload.get("anchor_bookmark")
        resume = payload.get("resume_bookmark")
        in_progress = payload.get("in_progress")
        replaying = payload.get("replaying_overlap")
        overlap_ready = payload.get("overlap_ready")
        lower_bound = payload.get("lower_bound_bookmark")
        recent_payload = payload.get("recent_bookmarks", [])
        if payload.get("version") == 1:
            # A versão anterior não distinguia um corte inicial de um cursor
            # comum. Usar o anchor confirmado como limite é conservador: não
            # perde eventos posteriores e impede que o primeiro overlap após a
            # migração atravesse um possível corte "a partir de agora".
            lower_bound = anchor
            recent_payload = [anchor] if anchor and overlap_ready else []
        if not isinstance(log_identity, str) or not log_identity:
            raise InvalidCheckpointError("Checkpoint não possui identidade do log")
        if anchor is not None and (not isinstance(anchor, str) or not anchor.strip()):
            raise InvalidCheckpointError("Checkpoint possui anchor_bookmark inválido")
        if resume is not None and (not isinstance(resume, str) or not resume.strip()):
            raise InvalidCheckpointError("Checkpoint possui resume_bookmark inválido")
        if lower_bound is not None and (
            not isinstance(lower_bound, str) or not lower_bound.strip()
        ):
            raise InvalidCheckpointError("Checkpoint possui limite inferior inválido")
        if not isinstance(recent_payload, list) or any(
            not isinstance(item, str) or not item.strip() for item in recent_payload
        ):
            raise InvalidCheckpointError("Checkpoint possui histórico de overlap inválido")
        if (
            not isinstance(in_progress, bool)
            or not isinstance(replaying, bool)
            or not isinstance(overlap_ready, bool)
        ):
            raise InvalidCheckpointError("Checkpoint possui estado de leitura inválido")
        if in_progress and resume is None:
            raise InvalidCheckpointError("Leitura em andamento exige resume_bookmark")
        if replaying and not in_progress:
            raise InvalidCheckpointError("Sobreposição exige leitura em andamento")
        if replaying and anchor is None:
            raise InvalidCheckpointError("Sobreposição exige anchor_bookmark")
        return cls(
            channel,
            log_identity,
            anchor,
            resume,
            in_progress,
            replaying,
            overlap_ready,
            lower_bound,
            tuple(recent_payload),
        )


def _bookmark_identity(bookmark: str) -> object:
    """Normaliza o XML do bookmark somente para reconhecer o mesmo registro."""
    try:
        root = ElementTree.fromstring(bookmark)
    except ElementTree.ParseError:
        return bookmark.strip()
    items: list[tuple[str, tuple[tuple[str, str], ...]]] = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "Bookmark":
            items.append((tag, tuple(sorted(element.attrib.items()))))
    return tuple(items) if items else bookmark.strip()


class WindowsEventLogSource:
    """Fonte incremental que consulta somente um canal local do Windows."""

    def __init__(
        self,
        channel: str = "ForwardedEvents",
        *,
        overlap_size: int = DEFAULT_OVERLAP_SIZE,
        backend: LocalEventLogBackend | None = None,
        generation_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(channel, str) or not channel.strip():
            raise ValueError("channel não pode ser vazio")
        if isinstance(overlap_size, bool) or not isinstance(overlap_size, int):
            raise ValueError("overlap_size deve ser um número inteiro")
        if not 0 <= overlap_size <= MAX_OVERLAP_SIZE:
            raise ValueError(
                f"overlap_size deve estar entre 0 e {MAX_OVERLAP_SIZE}"
            )
        self.channel = channel.strip()
        self.source = self.channel.casefold()
        self.overlap_size = overlap_size
        self.backend = backend or PyWin32EventLogBackend()
        self._generation_factory = generation_factory or (lambda: uuid.uuid4().hex)
        event_filter = " or ".join(
            f"EventID={event_id}" for event_id in sorted(EVENT_DEFINITIONS)
        )
        self.xpath_query = f"*[System[({event_filter})]]"

    def checkpoint_at_end(self) -> EventCheckpoint:
        """Cria, de forma explícita, o marco inicial no fim do log elegível atual."""
        log_identity = self.backend.log_identity(self.channel)
        anchor = self.backend.latest_bookmark(self.channel, self.xpath_query)
        generation = self._new_generation(log_identity)
        cursor = _Cursor(
            channel=self.source,
            log_identity=log_identity,
            anchor_bookmark=anchor,
            resume_bookmark=None,
            in_progress=False,
            replaying_overlap=False,
            overlap_ready=False,
            lower_bound_bookmark=anchor,
            recent_bookmarks=(),
        )
        return EventCheckpoint(self.source, cursor.encode(), generation, 0)

    def _new_generation(self, log_identity: str) -> str:
        nonce = self._generation_factory()
        if not isinstance(nonce, str) or not nonce.strip():
            raise RuntimeError("generation_factory retornou valor inválido")
        digest = hashlib.sha256(
            f"{self.source}|{log_identity}|{nonce.strip()}".encode("utf-8")
        ).hexdigest()
        return f"wel-v1-{digest}"

    def _initial_checkpoint(
        self,
        generation: str,
        log_identity: str,
    ) -> EventCheckpoint:
        return EventCheckpoint(
            self.source,
            _Cursor(
                channel=self.source,
                log_identity=log_identity,
                anchor_bookmark=None,
                resume_bookmark=None,
                in_progress=False,
                replaying_overlap=False,
                overlap_ready=True,
                lower_bound_bookmark=None,
                recent_bookmarks=(),
            ).encode(),
            generation,
            0,
        )

    def read_new_events(
        self,
        checkpoint: EventCheckpoint | None,
        *,
        limit: int,
    ) -> EventBatch:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit deve ser um número inteiro")
        if not 1 <= limit <= MAX_EVENT_BATCH_SIZE:
            raise ValueError(
                f"limit deve estar entre 1 e {MAX_EVENT_BATCH_SIZE}"
            )
        if checkpoint is not None and checkpoint.source != self.source:
            raise InvalidCheckpointError("Checkpoint pertence a outra fonte")

        log_identity = self.backend.log_identity(self.channel)
        generation_changed = checkpoint is None
        if checkpoint is None:
            generation = self._new_generation(log_identity)
            sequence = 0
            cursor = _Cursor(
                channel=self.source,
                log_identity=log_identity,
                anchor_bookmark=None,
                resume_bookmark=None,
                in_progress=False,
                replaying_overlap=False,
                overlap_ready=True,
                lower_bound_bookmark=None,
                recent_bookmarks=(),
            )
        else:
            generation = checkpoint.generation
            sequence = checkpoint.sequence
            cursor = _Cursor.decode(
                checkpoint.value,
                channel=self.source,
                current_log_identity=log_identity,
                legacy=checkpoint.generation == "legacy",
            )
            if cursor.log_identity != log_identity:
                LOGGER.warning(
                    "Nova geração do Event Log local detectada para o canal %s",
                    self.channel,
                )
                generation_changed = True
                generation = self._new_generation(log_identity)
                sequence = 0
                cursor = _Cursor(
                    channel=self.source,
                    log_identity=log_identity,
                    anchor_bookmark=None,
                    resume_bookmark=None,
                    in_progress=False,
                    replaying_overlap=False,
                    overlap_ready=True,
                    lower_bound_bookmark=None,
                    recent_bookmarks=(),
                )

        try:
            return self._read_from_cursor(
                cursor,
                generation=generation,
                sequence=sequence,
                limit=limit,
                generation_changed=generation_changed,
            )
        except InvalidBookmarkError as exc:
            if cursor.anchor_bookmark is None and cursor.resume_bookmark is None:
                raise
            LOGGER.warning(
                "Bookmark do Event Log local ficou inválido no canal %s; "
                "iniciando nova geração; reason_code=%s",
                self.channel,
                exc.reason_code,
            )
            new_generation = self._new_generation(log_identity)
            reset_cursor = _Cursor(
                channel=self.source,
                log_identity=log_identity,
                anchor_bookmark=None,
                resume_bookmark=None,
                in_progress=False,
                replaying_overlap=False,
                overlap_ready=True,
                lower_bound_bookmark=None,
                recent_bookmarks=(),
            )
            return self._read_from_cursor(
                reset_cursor,
                generation=new_generation,
                sequence=0,
                limit=limit,
                generation_changed=True,
            )

    def _read_from_cursor(
        self,
        cursor: _Cursor,
        *,
        generation: str,
        sequence: int,
        limit: int,
        generation_changed: bool,
    ) -> EventBatch:
        if cursor.in_progress:
            after_bookmark = cursor.resume_bookmark
            overlap = 0
            replaying = cursor.replaying_overlap
        else:
            if cursor.overlap_ready and cursor.recent_bookmarks:
                after_bookmark = cursor.recent_bookmarks[0]
                overlap = 1
            else:
                after_bookmark = cursor.anchor_bookmark
                overlap = 0
            replaying = overlap > 0

        page = self.backend.read_events(
            self.channel,
            self.xpath_query,
            after_bookmark=after_bookmark,
            overlap=overlap,
            limit=limit,
        )
        if not page.records:
            if generation_changed:
                return EventBatch(
                    (),
                    self._initial_checkpoint(generation, cursor.log_identity),
                )
            return EventBatch(
                (),
                None
                if cursor.in_progress
                else self._checkpoint(cursor, generation, sequence),
            )

        collected: list[CollectedEvent] = []
        anchor = cursor.anchor_bookmark
        recent = list(cursor.recent_bookmarks)
        anchor_identity = (
            _bookmark_identity(anchor) if anchor is not None and replaying else None
        )
        for index, record in enumerate(page.records):
            if replaying and _bookmark_identity(record.bookmark) == anchor_identity:
                replaying = False
            elif not replaying:
                anchor = record.bookmark

            record_identity = _bookmark_identity(record.bookmark)
            recent = [
                item
                for item in recent
                if _bookmark_identity(item) != record_identity
            ]
            recent.append(record.bookmark)
            if self.overlap_size == 0:
                recent = []
            elif len(recent) > self.overlap_size:
                recent = recent[-self.overlap_size :]

            is_last = index == len(page.records) - 1
            in_progress = page.has_more if is_last else True
            item_cursor = _Cursor(
                channel=self.source,
                log_identity=cursor.log_identity,
                anchor_bookmark=anchor,
                resume_bookmark=record.bookmark if in_progress else None,
                in_progress=in_progress,
                replaying_overlap=replaying if in_progress else False,
                overlap_ready=True,
                lower_bound_bookmark=cursor.lower_bound_bookmark,
                recent_bookmarks=tuple(recent),
            )
            item_checkpoint = EventCheckpoint(
                self.source,
                item_cursor.encode(),
                generation,
                sequence + index + 1,
            )
            collected.append(CollectedEvent(record.xml, item_checkpoint))

        if replaying and not page.has_more:
            # O bookmark validado deveria necessariamente aparecer na janela. Se não
            # apareceu, confirmar qualquer posição poderia saltar dados.
            raise InvalidBookmarkError("anchor_not_found")
        return EventBatch(
            tuple(collected),
            collected[-1].checkpoint,
            page.has_more,
        )

    @staticmethod
    def _checkpoint(
        cursor: _Cursor,
        generation: str,
        sequence: int,
    ) -> EventCheckpoint:
        return EventCheckpoint(
            cursor.channel,
            cursor.encode(),
            generation,
            sequence,
        )


def _windows_error_code(exc: BaseException) -> int | None:
    value = getattr(exc, "winerror", None)
    if isinstance(value, int):
        return value
    if exc.args and isinstance(exc.args[0], int):
        return int(exc.args[0])
    return None


class PyWin32EventLogBackend:
    """Backend da API moderna do Windows Event Log, sempre com sessão local."""

    _ERROR_NOT_FOUND = 1168
    _INVALID_BOOKMARK_CODES = frozenset({13, 15008, 15011})

    def __init__(self, api: object | None = None) -> None:
        self._api = api

    def _load_api(self):
        if self._api is not None:
            return self._api
        if os.name != "nt":
            raise EventLogReadError("windows_required")
        try:
            import win32evtlog
        except ImportError as exc:  # pragma: no cover - depende do Rigel
            raise EventLogReadError("pywin32_not_installed") from exc
        self._api = win32evtlog
        return self._api

    @staticmethod
    def _close(handle: object | None) -> None:
        if handle is not None:
            close = getattr(handle, "Close", None)
            if callable(close):
                close()

    def log_identity(self, channel: str) -> str:
        api = self._load_api()
        handle = None
        try:
            handle = api.EvtOpenLog(
                channel,
                api.EvtOpenChannelPath,
                Session=None,
            )
            creation_time, _ = api.EvtGetLogInfo(handle, api.EvtLogCreationTime)
            stable_time = (
                creation_time.isoformat()
                if hasattr(creation_time, "isoformat")
                else str(creation_time)
            )
            return hashlib.sha256(
                f"{channel.casefold()}|{stable_time}".encode("utf-8")
            ).hexdigest()
        except EventLogReadError:
            raise
        except Exception as exc:  # pragma: no cover - depende do Rigel
            raise EventLogReadError(
                "log_identity_failed",
                windows_error=_windows_error_code(exc),
            ) from exc
        finally:
            self._close(handle)

    def read_events(
        self,
        channel: str,
        xpath_query: str,
        *,
        after_bookmark: str | None,
        overlap: int,
        limit: int,
    ) -> EventLogPage:
        api = self._load_api()
        result = None
        bookmark_handle = None
        event_handles: tuple[object, ...] = ()
        try:
            result = api.EvtQuery(
                channel,
                api.EvtQueryChannelPath | api.EvtQueryForwardDirection,
                xpath_query,
                Session=None,
            )
            if after_bookmark is not None:
                try:
                    bookmark_handle = api.EvtCreateBookmark(after_bookmark)
                    api.EvtSeek(
                        result,
                        0,
                        api.EvtSeekRelativeToBookmark | api.EvtSeekStrict,
                        bookmark_handle,
                        0,
                    )
                except Exception as exc:
                    code = _windows_error_code(exc)
                    if code in self._INVALID_BOOKMARK_CODES | {self._ERROR_NOT_FOUND}:
                        raise InvalidBookmarkError(
                            "bookmark_not_found",
                            windows_error=code,
                        ) from exc
                    raise EventLogReadError(
                        "bookmark_validation_failed",
                        windows_error=code,
                    ) from exc

                if overlap > 0:
                    # Sem EvtSeekStrict: se a janela ultrapassar o início do log,
                    # a própria API fixa a posição no primeiro resultado disponível.
                    api.EvtSeek(
                        result,
                        -(overlap - 1),
                        api.EvtSeekRelativeToBookmark,
                        bookmark_handle,
                        0,
                    )
                else:
                    try:
                        api.EvtSeek(
                            result,
                            1,
                            api.EvtSeekRelativeToBookmark | api.EvtSeekStrict,
                            bookmark_handle,
                            0,
                        )
                    except Exception as exc:
                        if _windows_error_code(exc) == self._ERROR_NOT_FOUND:
                            return EventLogPage((), False)
                        raise

            event_handles = tuple(api.EvtNext(result, limit + 1, 0, 0))
            records: list[EventLogRecord] = []
            for event_handle in event_handles[:limit]:
                xml = api.EvtRender(event_handle, api.EvtRenderEventXml)
                item_bookmark = api.EvtCreateBookmark(None)
                try:
                    api.EvtUpdateBookmark(item_bookmark, event_handle)
                    bookmark_xml = api.EvtRender(
                        item_bookmark,
                        api.EvtRenderBookmark,
                    )
                finally:
                    self._close(item_bookmark)
                records.append(EventLogRecord(str(xml), str(bookmark_xml)))
            return EventLogPage(tuple(records), len(event_handles) > limit)
        except (InvalidBookmarkError, EventLogReadError):
            raise
        except Exception as exc:  # pragma: no cover - depende do Rigel
            raise EventLogReadError(
                "query_failed",
                windows_error=_windows_error_code(exc),
            ) from exc
        finally:
            for event_handle in event_handles:
                self._close(event_handle)
            self._close(bookmark_handle)
            self._close(result)

    def latest_bookmark(self, channel: str, xpath_query: str) -> str | None:
        api = self._load_api()
        result = None
        event_handle = None
        bookmark_handle = None
        try:
            result = api.EvtQuery(
                channel,
                api.EvtQueryChannelPath | api.EvtQueryReverseDirection,
                xpath_query,
                Session=None,
            )
            events = tuple(api.EvtNext(result, 1, 0, 0))
            if not events:
                return None
            event_handle = events[0]
            bookmark_handle = api.EvtCreateBookmark(None)
            api.EvtUpdateBookmark(bookmark_handle, event_handle)
            return str(api.EvtRender(bookmark_handle, api.EvtRenderBookmark))
        except EventLogReadError:
            raise
        except Exception as exc:  # pragma: no cover - depende do Rigel
            raise EventLogReadError(
                "latest_bookmark_failed",
                windows_error=_windows_error_code(exc),
            ) from exc
        finally:
            self._close(bookmark_handle)
            self._close(event_handle)
            self._close(result)
