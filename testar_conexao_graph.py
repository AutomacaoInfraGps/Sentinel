from __future__ import annotations

import argparse
import sys

from graph_email_service import GraphEmailService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Testa a conexao Microsoft Graph usada para o envio do dashboard consolidado.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Inicia autenticacao device code caso nao exista token em cache.",
    )
    parser.add_argument(
        "--destinatario",
        help="Se informado, envia um email simples de teste para validar o transporte.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    service = GraphEmailService()

    if not service.is_configured():
        missing = ", ".join(service.config.missing_fields)
        print(
            "[ERRO] Configuracao Microsoft Graph incompleta. "
            f"Preencha environment.json ou variaveis de ambiente: {missing}."
        )
        return 1

    try:
        profile = service.get_profile(interactive=args.interactive)
        display_name = str(profile.get("displayName") or "").strip() or "(sem nome)"
        upn = str(profile.get("userPrincipalName") or profile.get("mail") or "").strip() or "(sem UPN)"

        print("[OK] Conexao Microsoft Graph estabelecida.")
        print(f"   - Modo de autenticacao: {service.config.auth_mode}")
        print(f"   - Usuario autenticado: {display_name}")
        print(f"   - UPN: {upn}")
        print(f"   - Cache: {service.config.token_cache_path}")

        if args.destinatario:
            service.send_mail(
                recipients=[args.destinatario],
                subject="[Teste] Conexao Graph Sentinel",
                html_body=(
                    "<p>Conexao Microsoft Graph validada com sucesso no projeto Sentinel.</p>"
                    f"<p>Usuario autenticado: {display_name} ({upn})</p>"
                ),
                interactive=False,
            )
            print(f"[OK] Email de teste enviado para: {args.destinatario}")

        return 0
    except Exception as exc:
        print(f"[ERRO] {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
