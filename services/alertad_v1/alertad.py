from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))

# `python -m unittest discover -s tests` importa módulos de teste como módulos de
# topo. Nesse modo, este lançador pode ser encontrado antes do pacote `src/alertad`.
# Torná-lo um package shim quando importado evita o sombreamento; quando executado
# como script, o fluxo normal abaixo permanece inalterado.
if __name__ == "alertad":
    __path__ = [str(SOURCE_ROOT / "alertad")]

from alertad.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

