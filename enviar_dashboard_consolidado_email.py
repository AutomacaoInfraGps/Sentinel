from __future__ import annotations

import argparse
import html
import logging
import mimetypes
from datetime import datetime
from pathlib import Path

from config import ENV_CONFIG, RELATORIO_PREVENTIVA_DIR, ensure_directories, get_log_file
from graph_email_service import GraphEmailService


DEFAULT_RECIPIENT = "infraregional@gpssa.com.br"


def _configure_logging() -> Path:
    ensure_directories()
    log_file = get_log_file("envio_dashboard_consolidado_email")

    logger = logging.getLogger()
    logger.handlers.clear()
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return log_file


def _normalize_recipients(raw_value: str) -> list[str]:
    recipients: list[str] = []
    seen: set[str] = set()
    for item in str(raw_value or "").split(","):
        email = item.strip()
        if not email or "@" not in email:
            continue
        key = email.lower()
        if key in seen:
            continue
        seen.add(key)
        recipients.append(email)
    return recipients


def _load_recipients(cli_value: str | None) -> list[str]:
    if cli_value:
        return _normalize_recipients(cli_value)

    dashboard_config = ENV_CONFIG.get("dashboard_email", {}) or {}
    configured = dashboard_config.get("to", [])
    if isinstance(configured, list):
        recipients = _normalize_recipients(",".join(str(item or "") for item in configured)
        )
    else:
        recipients = _normalize_recipients(str(configured or ""))

    return recipients or [DEFAULT_RECIPIENT]


def _find_today_dashboard(report_path: str | None) -> Path:
    if report_path:
        candidate = Path(report_path).expanduser()
        if not candidate.exists():
            raise FileNotFoundError(f"Arquivo informado nao encontrado: {candidate}")
        return candidate

    files = sorted(RELATORIO_PREVENTIVA_DIR.glob("relatorio_preventiva_*.html"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(
            f"Nenhum dashboard consolidado foi encontrado para hoje em {RELATORIO_PREVENTIVA_DIR}"
        )
    return files[0]


def _to_drive_relative_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":")
    if not drive:
        return str(resolved)

    relative = resolved.relative_to(Path(f"{drive}:\\"))
    return f"{drive.lower()}\\{str(relative)}"


def _build_signature_html(service: GraphEmailService) -> tuple[str, list[dict]]:
    reply_to = html.escape(service.config.reply_to)

    signature_html = (
        "<div style='margin-top:18px;'>"
        "<strong>Gestão de Acessos de TI</strong><br>"
        "Gestão de Acessos | Governança de TI<br>"
        f"{reply_to}<br>"
        "</div>"
    )
    return signature_html, []

def _build_email_html(service: GraphEmailService, report_file: Path) -> tuple[str, list[dict]]:
    report_date = datetime.now().strftime("%d/%m/%Y")
    report_path = html.escape(_to_drive_relative_path(report_file))
    signature_html, signature_attachments = _build_signature_html(service)

    html_body = (
        "<div style='font-family:Segoe UI, Arial, sans-serif; font-size:14px; color:#1f2937;'>"
        "<p>Pessoal, bom dia!</p>"
        f"<p>Checklist feito no dia {report_date} concluído. Segue as evidências no dashboard consolidado:</p>"
        f"<p><strong>Arquivo do dia:</strong> {html.escape(report_file.name)}</p>"
        f"<p><strong>Caminho do arquivo:</strong> {report_path}</p>"
        "<p>O arquivo gerado hoje segue anexado neste e-mail.</p>"
        f"{signature_html}"
        "</div>"
    )

    attachment_content_type = mimetypes.guess_type(report_file.name)[0] or "text/html"
    report_attachment = {
        "name": report_file.name,
        "content_type": attachment_content_type,
        "data": report_file.read_bytes(),
    }
    return html_body, [report_attachment, *signature_attachments]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Envia por email o dashboard consolidado gerado no dia atual.",
    )
    parser.add_argument("--arquivo", help="Caminho explicito do HTML a anexar.")
    parser.add_argument("--destinatario", help="Sobrescreve o destinatario padrao do email.")
    parser.add_argument("--assunto", help="Sobrescreve o assunto padrao.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Nao envia o email; apenas valida arquivo, destinatario e corpo.",
    )
    return parser

def main() -> int:
    args = build_parser().parse_args()
    log_file = _configure_logging()
    service = GraphEmailService()

    if not service.is_configured():
        missing = ", ".join(service.config.missing_fields)
        logging.error("Configuracao Microsoft Graph incompleta: %s", missing)
        print(f"[ERRO] Configuracao Microsoft Graph incompleta: {missing}")
        print(f"   - Log: {log_file}")
        return 1

    try:
        report_file = _find_today_dashboard(args.arquivo)
        recipients = _load_recipients(args.destinatario)
        subject = args.assunto or f"Checklist Diário - Dashboard Consolidado - {datetime.now():%d/%m/%Y}"
        html_body, attachments = _build_email_html(service, report_file)

        logging.info("Inicio do envio do dashboard consolidado")
        logging.info("Remetente: %s", service.config.sender_upn)
        logging.info("Destinatarios: %s", ", ".join(recipients))
        logging.info("Arquivo selecionado: %s", report_file)
        logging.info("Modo de autenticacao: %s", service.config.auth_mode)
        logging.info("Cache configurado: %s", service.config.token_cache_path)

        if args.dry_run:
            logging.info("Dry-run executado com sucesso")
            print("[OK] Dry-run do email do dashboard consolidado")
            print(f"   - Remetente: {service.config.sender_upn}")
            print(f"   - Destinatarios: {', '.join(recipients)}")
            print(f"   - Arquivo: {report_file}")
            print(f"   - Cache configurado: {service.config.token_cache_path}")
            print(f"   - Modo de autenticacao: {service.config.auth_mode}")
            print(f"   - Log: {log_file}")
            return 0

        service.send_mail(
            recipients=recipients,
            subject=subject,
            html_body=html_body,
            attachments=attachments,
            reply_to=[service.config.reply_to] if service.config.reply_to else None,
        )
        logging.info("Email enviado com sucesso para %s", ", ".join(recipients))
        print(f"[OK] Email enviado para: {', '.join(recipients)}")
        print(f"   - Arquivo anexado: {report_file}")
        print(f"   - Log: {log_file}")
        return 0
    except Exception as exc:
        logging.exception("Falha no envio do dashboard consolidado")
        print(f"[ERRO] {exc}")
        print(f"   - Log: {log_file}")
        return 2

if __name__ == "__main__":
    raise SystemExit(main())