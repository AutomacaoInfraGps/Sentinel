import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


from services.access_review_v1.notifications import (
    AuditPayloadError,
    load_access_review_notifications,
    sanitize_audit_payload,
    store_audit_execution,
)


def valid_payload(**changes):
    payload = {
        "execucao_id": "550e8400-e29b-41d4-a716-446655440000",
        "origem": "automacao-auditoria",
        "titulo": "[SUCESSO] Auditorias Galaxia",
        "mensagem": "Resumo seguro da execucao",
        "status": "SUCESSO",
        "severidade": "informacao",
        "data": "2026-10-19T09:41:37-03:00",
        "resumo": {
            "executado_em": "2026-10-19T09:41:37-03:00",
            "somente_montagem": False,
            "navegador_compartilhado": True,
            "documentos_validos": True,
            "prints_removidos": 42,
            "auditorias": [{
                "id": "linux",
                "nome": "Linux",
                "status": "OK",
                "tentativas": 1,
                "inicio": "2026-10-19T09:22:35-03:00",
                "fim": "2026-10-19T09:23:52-03:00",
            }],
            "documentos": ["C:\\segredo\\resultado.docx"],
            "logs": ["C:\\segredo\\execucao.log"],
        },
        "campo_desconhecido": "nao persistir",
    }
    payload.update(changes)
    return payload


class AuditNotificationServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "audits.sqlite3"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_sanitizes_unknown_fields_paths_and_builds_success_notification(self):
        sanitized = sanitize_audit_payload(valid_payload())
        encoded = json.dumps(sanitized)
        self.assertNotIn('"documentos":', encoded)
        self.assertNotIn('"logs":', encoded)
        self.assertNotIn("campo_desconhecido", encoded)
        self.assertNotIn("C:\\segredo", encoded)

        event_id, created = store_audit_execution(valid_payload(), path=self.database)
        self.assertTrue(created)
        self.assertEqual(event_id, "550e8400-e29b-41d4-a716-446655440000")
        notifications = load_access_review_notifications(authorized=True, path=self.database)
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["severity"], "success")
        self.assertEqual(notifications[0]["type"], "audit_automation")
        self.assertEqual(notifications[0]["message"], "Linux: SUCESSO")
        self.assertEqual(notifications[0]['duration_seconds'], 77)
        self.assertNotIn("Prints", notifications[0]["message"])
        self.assertIn("?execucao=550e8400-e29b-41d4-a716-446655440000", notifications[0]["url"])

    def test_failure_is_critical_and_contains_only_friendly_error(self):
        payload = valid_payload(status="FALHA", titulo="Auditorias com falha")
        payload["resumo"]["auditorias"][0].update(
            status="FALHA", erro_amigavel="Portal indisponivel"
        )
        store_audit_execution(payload, path=self.database)
        notification = load_access_review_notifications(authorized=True, path=self.database)[0]
        self.assertEqual(notification["severity"], "critical")
        self.assertNotIn("Portal indisponivel", notification["message"])
        self.assertEqual(notification["message"], "Linux: FALHA")
        self.assertLess(len(notification["message"]), 120)

    def test_summary_lists_each_area_alphabetically_without_error_details(self):
        payload = valid_payload(status='FALHA')
        template = payload['resumo']['auditorias'][0]
        payload['resumo']['auditorias'] = [
            dict(template, id=area, nome=area, status=status, erro_amigavel='Detalhe reservado ao log')
            for area, status in [('windows', 'FALHA'), ('linux', 'FALHA'),
                                 ('firewalls', 'FALHA'), ('admanager', 'OK')]
        ]
        store_audit_execution(payload, path=self.database)
        notification = load_access_review_notifications(authorized=True, path=self.database)[0]
        self.assertEqual(notification['title'], 'Revisão de Acessos - Resumo:')
        self.assertEqual(notification['message'],
                         'AD Manager: SUCESSO\nAD Windows: FALHA\nFirewall: FALHA\nLinux: FALHA')

    def test_is_idempotent_and_hidden_from_non_operators(self):
        self.assertTrue(store_audit_execution(valid_payload(), path=self.database)[1])
        self.assertFalse(store_audit_execution(valid_payload(), path=self.database)[1])
        self.assertEqual(load_access_review_notifications(authorized=False, path=self.database), [])
        self.assertEqual(len(load_access_review_notifications(authorized=True, path=self.database)), 1)

    def test_rejects_invalid_origin_types_and_limits(self):
        with self.assertRaises(AuditPayloadError):
            sanitize_audit_payload(valid_payload(origem="outro-servico"))
        with self.assertRaises(AuditPayloadError):
            sanitize_audit_payload(valid_payload(mensagem=123))
        with self.assertRaises(AuditPayloadError):
            sanitize_audit_payload(valid_payload(mensagem="x" * 2001))

    def test_retention_removes_old_records(self):
        old_now = datetime(2025, 1, 1, tzinfo=timezone.utc)
        store_audit_execution(valid_payload(), path=self.database, now=old_now)
        second = valid_payload(execucao_id="new-execution")
        second["data"] = "2026-10-19T10:00:00-03:00"
        with patch("services.access_review_v1.notifications._retention_days", return_value=30):
            store_audit_execution(second, path=self.database, now=old_now + timedelta(days=31))
        notifications = load_access_review_notifications(authorized=True, path=self.database)
        self.assertEqual([item["id"] for item in notifications], ["auditoria:new-execution"])



if __name__ == "__main__":
    unittest.main()
