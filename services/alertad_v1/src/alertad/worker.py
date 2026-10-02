from __future__ import annotations

import hashlib
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping

from .config import RetentionPolicy
from .contracts import (
    CheckpointAdvance,
    DirectoryResolver,
    EventCheckpoint,
    EventSource,
    Notifier,
    OccurrenceCategory,
    OperationalOccurrence,
)
from .event_source import EventLogReadError
from .formatting import format_alert
from .parsing import EventParseError, UnsupportedEventError, parse_windows_event
from .persistence import Delivery, EventStore
from .rules import GroupMatcher


LOGGER = logging.getLogger(__name__)
RETRY_DELAYS_SECONDS = (30, 30, 30, 300, 900)


class WorkerAlreadyRunningError(RuntimeError):
    """Outra instância já detém o lock associado ao banco."""


class RetryPolicy:
    def delay_after_failure(
        self,
        attempt_number: int,
        *,
        retry_after_seconds: float | None = None,
    ) -> float | None:
        if attempt_number < 1:
            raise ValueError("attempt_number deve ser positivo")
        if attempt_number > len(RETRY_DELAYS_SECONDS):
            return None
        base = float(RETRY_DELAYS_SECONDS[attempt_number - 1])
        return max(base, retry_after_seconds or 0.0)


class WorkerInstanceLock:
    """Lock de SO vinculado ao banco, complementado por proteção entre threads."""

    _guard = threading.Lock()
    _held_paths: set[str] = set()

    def __init__(self, database_path: str | Path) -> None:
        database = Path(database_path).resolve(strict=False)
        self.database_path = database
        self.path = Path(f"{database}.worker.lock")
        self._file = None
        self._key = os.path.normcase(str(self.path))

    def acquire(self) -> None:
        try:
            if int(self.database_path.stat().st_nlink) != 1:
                raise ValueError(
                    "O banco SQLite não pode possuir hard links; "
                    "a exclusão de worker seria ambígua"
                )
        except FileNotFoundError:
            # O lock também é testável antes da inicialização do banco. O store
            # produtivo cria o arquivo antes de iniciar o worker.
            pass
        with self._guard:
            if self._key in self._held_paths:
                raise WorkerAlreadyRunningError("Worker já está ativo para este banco")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = self.path.open("a+b")
            try:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:  # pragma: no cover - caminho usado nos testes Linux/Unix
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, BlockingIOError) as exc:
                handle.close()
                raise WorkerAlreadyRunningError(
                    "Worker já está ativo para este banco"
                ) from exc
            self._held_paths.add(self._key)
            self._file = handle

    def release(self) -> None:
        with self._guard:
            handle = self._file
            if handle is None:
                return
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:  # pragma: no cover - caminho usado nos testes Linux/Unix
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
                self._file = None
                self._held_paths.discard(self._key)

    def __enter__(self) -> "WorkerInstanceLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


@dataclass
class WorkerMetrics:
    events_read: int = 0
    events_filtered: int = 0
    events_persisted: int = 0
    events_duplicate: int = 0
    events_invalid: int = 0
    directory_fallbacks: int = 0
    deliveries_sent: int = 0
    deliveries_failed: int = 0
    source_failures: int = 0
    max_delivery_latency_seconds: float = 0.0


def _checkpoint_advance(
    current: EventCheckpoint | None,
    next_checkpoint: EventCheckpoint,
) -> CheckpointAdvance:
    generation_change = (
        current is not None
        and current.generation != next_checkpoint.generation
    )
    return CheckpointAdvance(
        current,
        next_checkpoint,
        allow_generation_change=generation_change,
    )


class AlertWorker:
    def __init__(
        self,
        *,
        source: EventSource,
        store: EventStore,
        resolver: DirectoryResolver,
        matcher: GroupMatcher,
        channels: Iterable[str],
        notifiers: Mapping[str, Notifier] | None = None,
        batch_size: int = 500,
        poll_interval_seconds: float = 30,
        dry_run: bool = False,
        clock: Callable[[], datetime] | None = None,
        on_dry_run_message: Callable[[str], None] | None = None,
        retry_policy: RetryPolicy | None = None,
        retention: RetentionPolicy | None = None,
    ) -> None:
        if not 1 <= batch_size <= 500:
            raise ValueError("batch_size deve estar entre 1 e 500")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds deve ser maior que zero")
        if dry_run != (store.database_mode == "dry_run"):
            raise ValueError("Modo do worker deve corresponder ao modo do banco")
        self.source = source
        self.store = store
        self.resolver = resolver
        self.matcher = matcher
        self.channels = tuple(dict.fromkeys(value.strip().casefold() for value in channels))
        self.notifiers = {
            key.strip().casefold(): value for key, value in (notifiers or {}).items()
        }
        self.batch_size = batch_size
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.dry_run = dry_run
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.on_dry_run_message = on_dry_run_message
        self.retry_policy = retry_policy or RetryPolicy()
        self.retention = retention or RetentionPolicy()
        self._next_maintenance_at: datetime | None = None
        self.metrics = WorkerMetrics()

    def _record_invalid(
        self,
        xml: str,
        reason_code: str,
        advance: CheckpointAdvance,
    ) -> None:
        fingerprint = hashlib.sha256(
            f"{advance.next.source}|{xml}".encode("utf-8", errors="replace")
        ).hexdigest()
        occurrence = OperationalOccurrence(
            category=OccurrenceCategory.INVALID_EVENT,
            component="parser",
            reason_code=reason_code,
            fingerprint=fingerprint,
            occurred_at_utc=self.clock(),
            source=advance.next.source,
        )
        self.store.record_occurrence(occurrence, checkpoint_advance=advance)
        self.metrics.events_invalid += 1

    def ingest_available(self, stop_event: threading.Event | None = None) -> int:
        checkpoint = self.store.get_checkpoint(getattr(self.source, "source"))
        processed = 0
        while True:
            batch = self.source.read_new_events(checkpoint, limit=self.batch_size)
            if not batch.events:
                next_checkpoint = batch.next_checkpoint
                if next_checkpoint is not None and next_checkpoint != checkpoint:
                    self.store.advance_checkpoint(
                        _checkpoint_advance(checkpoint, next_checkpoint)
                    )
                    checkpoint = next_checkpoint
                break

            for collected in batch.events:
                if stop_event is not None and stop_event.is_set():
                    return processed
                self.metrics.events_read += 1
                advance = _checkpoint_advance(checkpoint, collected.checkpoint)
                try:
                    event = parse_windows_event(collected.xml)
                except UnsupportedEventError:
                    self._record_invalid(collected.xml, "unsupported_event", advance)
                except EventParseError:
                    self._record_invalid(collected.xml, "invalid_event_xml", advance)
                else:
                    if not self.matcher.matches(event):
                        self.store.advance_checkpoint(advance)
                        self.metrics.events_filtered += 1
                    else:
                        existing = self.store.get_event_snapshot(event.event_key)
                        if existing is not None and existing.complete:
                            self.store.advance_checkpoint(advance)
                            self.metrics.events_duplicate += 1
                        else:
                            # MemberName já é fornecido pelo evento em muitos
                            # cenários. A consulta ao diretório é apenas o
                            # enriquecimento de fallback quando esse campo está
                            # ausente (o parser também normaliza "-" para None).
                            resolution = None
                            if not event.member_name:
                                resolution = self.resolver.resolve_sid(event.member_sid)
                                if resolution.directory_object is None:
                                    self.metrics.directory_fallbacks += 1
                            message = format_alert(event, resolution)
                            inserted = self.store.add_event(
                                event,
                                self.channels,
                                message=message,
                                checkpoint_advance=advance,
                                directory_resolution=resolution,
                                enqueue_deliveries=not self.dry_run,
                            )
                            if inserted:
                                self.metrics.events_persisted += 1
                                if self.dry_run and self.on_dry_run_message is not None:
                                    try:
                                        self.on_dry_run_message(message)
                                    except Exception as exc:
                                        # A saída de demonstração ocorre depois do commit. Uma
                                        # falha no console não deve transformar um evento já
                                        # confirmado em uma falsa falha de processamento.
                                        LOGGER.error(
                                            "dry_run_output_failed exception_type=%s",
                                            type(exc).__name__,
                                        )
                            else:
                                self.metrics.events_duplicate += 1
                checkpoint = collected.checkpoint
                processed += 1
            if not batch.has_more:
                break
        return processed

    def _terminal_occurrence(
        self,
        delivery: Delivery,
        reason_code: str,
    ) -> OperationalOccurrence:
        fingerprint = hashlib.sha256(
            f"{delivery.event_key}|{delivery.channel}|{reason_code}".encode("utf-8")
        ).hexdigest()
        return OperationalOccurrence(
            category=OccurrenceCategory.PERMANENT_DELIVERY_ERROR,
            component=f"notifier.{delivery.channel}",
            reason_code=reason_code,
            fingerprint=fingerprint,
            occurred_at_utc=self.clock(),
            source=delivery.event_key[:12],
        )

    def dispatch_due(
        self,
        *,
        limit: int = 100,
        stop_event: threading.Event | None = None,
    ) -> int:
        if self.dry_run:
            return 0
        deliveries = self.store.pending_deliveries(limit=limit, now=self.clock())
        completed = 0
        for delivery in deliveries:
            if stop_event is not None and stop_event.is_set():
                break
            if delivery.attempts >= self.store.max_delivery_attempts:
                self.store.finalize_exhausted_uncertain(
                    delivery,
                    self._terminal_occurrence(
                        delivery,
                        "uncertain_final_result",
                    ),
                )
                self.metrics.deliveries_failed += 1
                completed += 1
                continue

            safety_delay = self.retry_policy.delay_after_failure(
                delivery.attempts + 1
            ) or RETRY_DELAYS_SECONDS[-1]
            now = self.clock()
            claimed = self.store.claim_delivery_attempt(
                delivery,
                started_at_utc=now,
                uncertainty_retry_at_utc=now + timedelta(seconds=safety_delay),
            )
            if claimed is None:
                continue
            try:
                notifier = self.notifiers.get(claimed.channel)
                snapshot = self.store.get_event_snapshot(claimed.event_key)
                if notifier is None or snapshot is None or not snapshot.complete:
                    reason = (
                        "notifier_not_configured"
                        if notifier is None
                        else "snapshot_unavailable"
                    )
                    self.store.complete_delivery_attempt(
                        claimed.event_key,
                        claimed.channel,
                        attempt_number=claimed.attempts,
                        success=False,
                        retryable=False,
                        error="Entrega não pode ser executada com a configuração atual",
                        failure_kind="permanent",
                        claim_token=claimed.claim_token,
                        terminal_occurrence=self._terminal_occurrence(claimed, reason),
                    )
                    self.metrics.deliveries_failed += 1
                    completed += 1
                    continue

                result = notifier.send(snapshot.to_event(), snapshot.message or "")
                completed_at = self.clock()
                if result.success:
                    self.store.complete_delivery_attempt(
                        claimed.event_key,
                        claimed.channel,
                        attempt_number=claimed.attempts,
                        success=True,
                        claim_token=claimed.claim_token,
                    )
                    self.metrics.deliveries_sent += 1
                    latency = max(
                        0.0,
                        (completed_at - snapshot.time_created_utc).total_seconds(),
                    )
                    self.metrics.max_delivery_latency_seconds = max(
                        self.metrics.max_delivery_latency_seconds,
                        latency,
                    )
                else:
                    delay = self.retry_policy.delay_after_failure(
                        claimed.attempts,
                        retry_after_seconds=result.retry_after_seconds,
                    )
                    will_retry = result.retryable and delay is not None
                    reason = (
                        "retry_exhausted"
                        if result.retryable
                        else "permanent_delivery_error"
                    )
                    terminal_occurrence = (
                        self._terminal_occurrence(claimed, reason)
                        if not will_retry
                        else None
                    )
                    terminal = self.store.complete_delivery_attempt(
                        claimed.event_key,
                        claimed.channel,
                        attempt_number=claimed.attempts,
                        success=False,
                        retryable=result.retryable,
                        error=result.error,
                        next_attempt_at_utc=(
                            completed_at + timedelta(seconds=delay)
                            if will_retry and delay is not None
                            else None
                        ),
                        failure_kind=result.failure_kind,
                        claim_token=claimed.claim_token,
                        terminal_occurrence=terminal_occurrence,
                    )
                    if terminal.status == "failed":
                        self.metrics.deliveries_failed += 1
            except Exception:
                try:
                    self.store.abandon_delivery_claim(claimed)
                except Exception as release_error:
                    LOGGER.error(
                        "delivery_claim_release_failed exception_type=%s",
                        type(release_error).__name__,
                    )
                raise
            completed += 1
        return completed

    def run_once(self) -> int:
        activity = 0
        try:
            activity += self.ingest_available()
        except EventLogReadError as exc:
            self.metrics.source_failures += 1
            LOGGER.error(
                "event_source_read_failed reason_code=%s windows_error=%s",
                exc.reason_code,
                exc.windows_error,
            )
            raise
        activity += self.dispatch_due()
        activity += self.run_maintenance()
        return activity

    def run_maintenance(self) -> int:
        if not self.retention.purge_enabled:
            return 0
        now = self.clock()
        if self._next_maintenance_at is not None and now < self._next_maintenance_at:
            return 0
        event_days = max(
            int(self.retention.events_and_deliveries_days or 0),
            int(self.retention.deduplication_guard_days or 0),
        )
        occurrence_days = int(self.retention.occurrences_days or 0)
        result = self.store.purge_completed(
            events_before_utc=now - timedelta(days=event_days),
            resolved_occurrences_before_utc=now - timedelta(days=occurrence_days),
            batch_size=500,
        )
        removed = result.events + result.occurrences
        # Backlogs de manutenção avançam em lotes, sem manter uma transação longa.
        self._next_maintenance_at = now + timedelta(
            seconds=self.poll_interval_seconds if removed >= 500 else 86400
        )
        return removed

    def run(self, stop_event: threading.Event) -> None:
        with WorkerInstanceLock(self.store.database_path):
            recovered_claims = self.store.recover_abandoned_claims()
            LOGGER.info("worker_started mode=%s", self.store.database_mode)
            if recovered_claims:
                LOGGER.warning("delivery_claims_recovered count=%s", recovered_claims)
            delivery_thread = threading.Thread(
                target=self._delivery_loop,
                args=(stop_event,),
                name="alertad-delivery",
                daemon=False,
            )
            delivery_thread.start()
            try:
                while not stop_event.is_set():
                    try:
                        self.ingest_available(stop_event)
                    except EventLogReadError as exc:
                        self.metrics.source_failures += 1
                        LOGGER.error(
                            "event_source_read_failed reason_code=%s windows_error=%s",
                            exc.reason_code,
                            exc.windows_error,
                        )
                    if not stop_event.is_set():
                        self.run_maintenance()
                    LOGGER.info(
                        "worker_metrics events_read=%s events_filtered=%s "
                        "events_persisted=%s events_duplicate=%s events_invalid=%s "
                        "directory_fallbacks=%s deliveries_sent=%s "
                        "deliveries_failed=%s source_failures=%s "
                        "max_delivery_latency_seconds=%.3f",
                        self.metrics.events_read,
                        self.metrics.events_filtered,
                        self.metrics.events_persisted,
                        self.metrics.events_duplicate,
                        self.metrics.events_invalid,
                        self.metrics.directory_fallbacks,
                        self.metrics.deliveries_sent,
                        self.metrics.deliveries_failed,
                        self.metrics.source_failures,
                        self.metrics.max_delivery_latency_seconds,
                    )
                    stop_event.wait(self.poll_interval_seconds)
            finally:
                stop_event.set()
                # Notificadores possuem timeout finito. Esperar a thread evita
                # liberar o lock enquanto uma entrega ainda está em andamento.
                delivery_thread.join()
                LOGGER.info("worker_stopped")

    def _delivery_loop(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            try:
                self.dispatch_due(stop_event=stop_event)
            except Exception as exc:
                # dispatch_due libera por CAS o claim da tentativa que falhou
                # internamente, preservando o prazo incerto já durável.
                LOGGER.error(
                    "delivery_cycle_failed exception_type=%s",
                    type(exc).__name__,
                )
            stop_event.wait(self.poll_interval_seconds)


def initialize_checkpoint_at_end(source, store: EventStore) -> EventCheckpoint:
    current = store.get_checkpoint(source.source)
    if current is not None:
        raise RuntimeError("Checkpoint inicial já existe; não capture um novo corte")
    checkpoint = source.checkpoint_at_end()
    store.advance_checkpoint(CheckpointAdvance(None, checkpoint))
    return checkpoint
