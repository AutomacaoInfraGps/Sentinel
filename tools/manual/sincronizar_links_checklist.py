from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _resumir(resultado):
    dados = resultado if isinstance(resultado, dict) else {}
    regionais = dados.get("regionais") or {}
    sucessos = sum(
        1
        for item in regionais.values()
        if isinstance(item, dict) and item.get("success")
    )
    falhas = sum(
        1
        for item in regionais.values()
        if isinstance(item, dict) and not item.get("success")
    )
    total_links = sum(
        int((item or {}).get("total_links") or 0)
        for item in regionais.values()
        if isinstance(item, dict)
    )
    return {
        "success": bool(dados.get("success")),
        "total_regionais": len(regionais),
        "sucessos": sucessos,
        "falhas": falhas,
        "total_links": total_links,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Sincroniza links de internet antes do checklist."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Valida importacao sem consultar FortiManager.",
    )
    args = parser.parse_args()

    try:
        from web_config import app, _executar_sincronizacao_links_todas_regionais
    except Exception as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "message": f"Falha ao importar sincronizador: {exc}",
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2

    if args.dry_run:
        print(
            json.dumps(
                {"success": True, "message": "Sincronizador de links disponivel."},
                ensure_ascii=False,
            )
        )
        return 0

    with app.app_context():
        resultado = _executar_sincronizacao_links_todas_regionais()

    resumo = _resumir(resultado)
    print(json.dumps(resumo, ensure_ascii=False, indent=2))
    return 0 if resumo["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
