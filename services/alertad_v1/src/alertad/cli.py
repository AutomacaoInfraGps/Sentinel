from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from dataclasses import asdict, replace
from pathlib import Path

from .config import Settings
from .directory import CachingDirectoryResolver, PowerShellADWSLookupClient
from .event_source import EventLogReadError, WindowsEventLogSource
from .formatting import format_alert
from .logging_setup import configure_logging
from .notifiers import GraphEmailNotifier, GraphTeamsNotifier
from .parsing import EventParseError, parse_windows_event
from .persistence import EventStore
from .reporting import export_attention_report
from .rules import GroupMatcher
from .sentinel_environment import load_sentinel_graph_environment
from .service import EventProcessor, ProcessStatus
from .worker import (
    AlertWorker,
    WorkerAlreadyRunningError,
    WorkerInstanceLock,
    initialize_checkpoint_at_end,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Alertas de grupos críticos do AD.")
    subcommands = parser.add_subparsers(dest="command", required=True)

    parse_command = subcommands.add_parser("parse", help="Lê e valida um arquivo XML.")
    parse_command.add_argument("xml_file", type=Path)
    parse_command.add_argument("--database", type=Path, help="Registra o evento e testa deduplicação.")
    parse_command.add_argument("--settings", type=Path, help="Arquivo JSON de configuração.")

    init_command = subcommands.add_parser("init-db", help="Inicializa o banco SQLite.")
    init_command.add_argument("database", type=Path)
    init_command.add_argument("--dry-run", action="store_true")

    report_command = subcommands.add_parser(
        "report",
        help="Exporta eventos com pontos de atenção para CSV.",
    )
    report_command.add_argument("database", type=Path)
    report_command.add_argument("output", type=Path)
    report_command.add_argument("--dry-run", action="store_true")

    worker_command = subcommands.add_parser(
        "worker",
        help="Executa coleta, processamento e entregas.",
    )
    worker_command.add_argument("database", type=Path)
    worker_command.add_argument("--settings", type=Path, required=True)
    worker_command.add_argument("--dry-run", action="store_true")
    worker_command.add_argument("--once", action="store_true")
    worker_command.add_argument("--initialize-at-end", action="store_true")
    worker_command.add_argument("--log-file", type=Path, default=Path("logs/alertad.jsonl"))
    worker_command.add_argument(
        "--env-file",
        type=Path,
        help="Arquivo local protegido com variáveis do Microsoft Graph.",
    )
    worker_command.add_argument(
        "--sentinel-environment",
        type=Path,
        help="environment.json local do Sentinel; valores Graph lidos em memoria.",
    )

    status_command = subcommands.add_parser("status", help="Mostra o estado local do banco.")
    status_command.add_argument("database", type=Path)
    status_command.add_argument("--dry-run", action="store_true")

    diagnose_command = subcommands.add_parser(
        "diagnose",
        help="Valida configuração e integridade local, sem acessar rede.",
    )
    diagnose_command.add_argument("database", type=Path)
    diagnose_command.add_argument("--settings", type=Path, required=True)
    diagnose_command.add_argument("--dry-run", action="store_true")

    simulation_command = subcommands.add_parser(
        "simulate-missing-member",
        help=(
            "Força MemberName ausente em um XML e testa a resolução ADWS "
            "com credencial temporária."
        ),
    )
    simulation_command.add_argument("xml_file", type=Path)
    simulation_command.add_argument("--settings", type=Path, required=True)

    occurrences = subcommands.add_parser(
        "occurrences",
        help="Lista ou resolve ocorrências operacionais.",
    )
    occurrence_commands = occurrences.add_subparsers(dest="occurrence_command", required=True)
    occurrence_list = occurrence_commands.add_parser("list")
    occurrence_list.add_argument("database", type=Path)
    occurrence_list.add_argument("--all", action="store_true")
    occurrence_list.add_argument("--limit", type=int, default=100)
    occurrence_list.add_argument("--dry-run", action="store_true")
    occurrence_resolve = occurrence_commands.add_parser("resolve")
    occurrence_resolve.add_argument("database", type=Path)
    occurrence_resolve.add_argument("occurrence_id", type=int)
    occurrence_resolve.add_argument("--dry-run", action="store_true")
    return parser


def _configure_output_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def _database_mode(args) -> str:
    return "dry_run" if getattr(args, "dry_run", False) else "production"


def _existing_store(path: Path, *, mode: str, max_attempts: int = 6) -> EventStore:
    if not path.exists():
        raise ValueError(f"Banco não encontrado: {path}")
    return EventStore(path, database_mode=mode, max_delivery_attempts=max_attempts)


def _directory_resolver(
    settings: Settings,
    *,
    interactive_credentials: bool = False,
) -> CachingDirectoryResolver:
    directory = settings.directory
    directory.validate_for_worker()
    client = PowerShellADWSLookupClient(
        server=directory.server,
        timeout_seconds=directory.query_timeout_seconds,
        interactive_credentials=interactive_credentials,
    )
    return CachingDirectoryResolver(
        client,
        cache_ttl_seconds=directory.cache_ttl_seconds,
        cache_max_entries=directory.cache_max_entries,
    )


def _notifiers(settings: Settings):
    result = {}
    if "teams" in settings.delivery_channels:
        result["teams"] = GraphTeamsNotifier.from_environment()
    if "email" in settings.delivery_channels:
        result["email"] = GraphEmailNotifier.from_environment()
    return result


def _run_worker(args) -> int:
    if args.env_file is not None:
        if not args.env_file.is_file():
            raise ValueError(f"Arquivo de ambiente não encontrado: {args.env_file}")
        try:
            from dotenv import load_dotenv
        except ImportError as exc:
            raise RuntimeError("Dependência 'python-dotenv' não instalada") from exc
        load_dotenv(args.env_file, override=False)
    if args.sentinel_environment is not None:
        load_sentinel_graph_environment(args.sentinel_environment)
    settings = Settings.load(args.settings)
    settings.validate_for_worker()
    configure_logging(args.log_file)
    mode = _database_mode(args)
    store = EventStore(
        args.database,
        max_delivery_attempts=settings.max_delivery_attempts,
        database_mode=mode,
    )
    source = WindowsEventLogSource(
        settings.event_log_channel,
        overlap_size=settings.event_overlap_size,
    )
    if args.initialize_at_end:
        initialize_checkpoint_at_end(source, store)
    worker = AlertWorker(
        source=source,
        store=store,
        resolver=_directory_resolver(settings),
        matcher=GroupMatcher(settings.fixed_groups, settings.group_name_prefix),
        channels=settings.delivery_channels,
        notifiers={} if args.dry_run else _notifiers(settings),
        batch_size=settings.event_batch_size,
        poll_interval_seconds=settings.poll_interval_seconds or 30,
        dry_run=args.dry_run,
        retention=settings.retention,
        on_dry_run_message=print if args.dry_run else None,
    )
    if args.once:
        with WorkerInstanceLock(store.database_path):
            store.recover_abandoned_claims()
            worker.run_once()
        print(json.dumps(asdict(worker.metrics), ensure_ascii=False, sort_keys=True))
        return 0

    stop_event = threading.Event()

    def request_stop(signum, frame) -> None:
        del signum, frame
        stop_event.set()

    for signal_name in ("SIGINT", "SIGTERM"):
        available = getattr(signal, signal_name, None)
        if available is not None:
            signal.signal(available, request_stop)
    worker.run(stop_event)
    return 0


def main() -> int:
    _configure_output_encoding()
    args = _build_parser().parse_args()
    try:
        if args.command == "init-db":
            EventStore(args.database, database_mode=_database_mode(args))
            print(f"Banco inicializado: {args.database}")
            return 0
        if args.command == "report":
            store = _existing_store(args.database, mode=_database_mode(args))
            total = export_attention_report(store, args.output)
            print(f"Relatório exportado: {args.output} ({total} registro(s))")
            return 0
        if args.command == "status":
            store = _existing_store(args.database, mode=_database_mode(args))
            print(json.dumps(store.operational_status(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "diagnose":
            settings = Settings.load(args.settings)
            settings.validate_for_worker()
            store = _existing_store(
                args.database,
                mode=_database_mode(args),
                max_attempts=settings.max_delivery_attempts,
            )
            result = {
                "settings_valid": True,
                **store.operational_status(),
            }
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "simulate-missing-member":
            settings = Settings.load(args.settings)
            settings.validate_for_worker()
            event = parse_windows_event(args.xml_file.read_text(encoding="utf-8-sig"))
            matcher = GroupMatcher(settings.fixed_groups, settings.group_name_prefix)
            if not matcher.matches(event):
                raise ValueError("Evento de teste pertence a grupo fora do escopo")
            simulated = replace(event, member_name=None)
            resolution = _directory_resolver(
                settings,
                interactive_credentials=True,
            ).resolve_sid(simulated.member_sid)
            print(
                json.dumps(
                    {
                        "directory_status": resolution.status.value,
                        "error_code": resolution.error_code,
                        "simulation": "member_name_missing_in_memory",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            print(format_alert(simulated, resolution))
            return 0
        if args.command == "occurrences":
            store = _existing_store(args.database, mode=_database_mode(args))
            if args.occurrence_command == "resolve":
                changed = store.resolve_occurrence(args.occurrence_id)
                print("Ocorrência resolvida." if changed else "Ocorrência não encontrada ou já resolvida.")
                return 0
            rows = store.list_occurrences(open_only=not args.all, limit=args.limit)
            print(
                json.dumps(
                    [
                        {
                            **asdict(row),
                            "occurred_at_utc": row.occurred_at_utc.isoformat(),
                            "resolved_at_utc": (
                                row.resolved_at_utc.isoformat()
                                if row.resolved_at_utc is not None
                                else None
                            ),
                        }
                        for row in rows
                    ],
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "worker":
            return _run_worker(args)

        settings = Settings.load(args.settings) if args.settings else Settings()
        store = (
            EventStore(
                args.database,
                max_delivery_attempts=settings.max_delivery_attempts,
            )
            if args.database
            else None
        )
        result = EventProcessor(
            matcher=GroupMatcher(settings.fixed_groups, settings.group_name_prefix),
            store=store,
            channels=settings.delivery_channels,
        ).process_xml(args.xml_file.read_text(encoding="utf-8-sig"))
    except (
        OSError,
        ValueError,
        RuntimeError,
        EventParseError,
        EventLogReadError,
        WorkerAlreadyRunningError,
    ) as exc:
        print(f"ERRO: {exc}")
        return 2

    if result.status is ProcessStatus.OUT_OF_SCOPE:
        print(f"Evento válido, mas grupo fora do escopo: {result.event.target_user_name}")
        return 0
    if result.status is ProcessStatus.DUPLICATE:
        print(f"Evento duplicado: {result.event.event_key[:12]}")
        return 0

    print(result.message)
    if store is not None:
        print("\nPersistência: evento novo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
