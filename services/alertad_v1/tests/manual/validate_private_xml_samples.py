from __future__ import annotations

import argparse
import sys
from pathlib import Path


ALERTAD_ROOT = Path(__file__).resolve().parents[2]
ALERTAD_SOURCE = ALERTAD_ROOT / "src"
sys.path.insert(0, str(ALERTAD_SOURCE))

from alertad.parsing import parse_windows_event  # noqa: E402
from alertad.persistence import EventStore  # noqa: E402
from alertad.rules import GroupMatcher  # noqa: E402
from alertad.service import EventProcessor, ProcessStatus  # noqa: E402


EXPECTED_FILES = (
    "4728.xml",
    "4729.xml",
    "4732.xml",
    "4733.xml",
    "4756.xml",
    "4757.xml",
)
EXPECTED_INVALID = frozenset({"4733.xml"})
EXPECTED_OUT_OF_SCOPE = frozenset({"4732.xml"})


class SampleValidationError(ValueError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Valida amostras XML privadas do AlertAD sem exibir campos dos eventos."
        )
    )
    parser.add_argument("samples_directory", type=Path)
    parser.add_argument(
        "--import-dry-run",
        type=Path,
        metavar="DATABASE",
        help=(
            "Após validar todas as amostras, importa somente as válidas em um "
            "banco AlertAD existente e marcado como dry_run."
        ),
    )
    return parser


def _validate_samples(directory: Path) -> tuple[dict[str, str], list[str]]:
    matcher = GroupMatcher()
    valid_xml: dict[str, str] = {}
    failures: list[str] = []

    if not directory.is_dir():
        return {}, ["diretório de amostras não encontrado"]

    for filename in EXPECTED_FILES:
        path = directory / filename
        if not path.is_file():
            print(f"[FALHA] {filename}: arquivo ausente")
            failures.append(filename)
            continue

        try:
            xml_text = path.read_text(encoding="utf-8-sig")
            event = parse_windows_event(xml_text)
            if event.event_id != int(path.stem):
                raise SampleValidationError("event_id_mismatch")
        except SampleValidationError as exc:
            if filename in EXPECTED_INVALID:
                print(
                    f"[OK] {filename}: inválido como esperado "
                    f"({exc.reason_code})"
                )
            else:
                print(f"[FALHA] {filename}: {exc.reason_code}")
                failures.append(filename)
            continue
        except Exception as exc:  # A mensagem pode conter dados sensíveis.
            if filename in EXPECTED_INVALID:
                print(
                    f"[OK] {filename}: inválido como esperado "
                    f"({type(exc).__name__})"
                )
            else:
                print(f"[FALHA] {filename}: inválido ({type(exc).__name__})")
                failures.append(filename)
            continue

        if filename in EXPECTED_INVALID:
            print(f"[FALHA] {filename}: deveria ser inválido")
            failures.append(filename)
            continue

        in_scope = matcher.matches(event)
        if filename in EXPECTED_OUT_OF_SCOPE:
            if in_scope:
                print(f"[FALHA] {filename}: deveria ficar fora do escopo")
                failures.append(filename)
            else:
                print(f"[OK] {filename}: válido e fora do escopo como esperado")
            continue

        if not in_scope:
            print(f"[FALHA] {filename}: group_out_of_scope")
            failures.append(filename)
            continue

        valid_xml[filename] = xml_text
        print(f"[OK] {filename}: válido e dentro do escopo")

    return valid_xml, failures


def _import_valid_samples(database: Path, samples: dict[str, str]) -> None:
    if not database.is_file():
        raise ValueError("banco dry_run não encontrado")

    store = EventStore(database, database_mode="dry_run")
    processor = EventProcessor(store=store)
    imported = 0
    duplicates = 0

    for filename in EXPECTED_FILES:
        xml_text = samples.get(filename)
        if xml_text is None:
            continue
        result = processor.process_xml(xml_text)
        if result.status is ProcessStatus.READY:
            imported += 1
        elif result.status is ProcessStatus.DUPLICATE:
            duplicates += 1
        else:
            raise RuntimeError(f"{filename} ficou fora do escopo durante a importação")

    status = store.operational_status()
    print(
        "Importação dry_run concluída: "
        f"novos={imported}, duplicados={duplicates}, "
        f"eventos_no_banco={status['events']}, "
        f"entregas_pendentes={status['pending']}"
    )


def main() -> int:
    args = _parser().parse_args()
    samples_directory = args.samples_directory.resolve(strict=False)
    valid_samples, failures = _validate_samples(samples_directory)
    if failures:
        print(f"Validação reprovada: {len(failures)} falha(s).")
        return 2

    print(
        f"Validação aprovada: {len(valid_samples)} importável(is), "
        f"{len(EXPECTED_OUT_OF_SCOPE)} fora do escopo e "
        f"{len(EXPECTED_INVALID)} inválido(s) esperado(s)."
    )
    if args.import_dry_run is None:
        print("Banco não alterado; use --import-dry-run para importar.")
        return 0

    try:
        _import_valid_samples(args.import_dry_run.resolve(strict=False), valid_samples)
    except Exception as exc:  # Não exponha conteúdo ou caminho sensível em erro.
        print(f"[FALHA] importação dry_run: {type(exc).__name__}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
