from __future__ import annotations

import unittest
from unittest.mock import patch
from pathlib import Path

from regional_access import ADMINISTRATIVE_OU_DN
from user_model import User, remove_user, save_user
from web_config import app


class SwitchUpdateFrontendTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()
        self.user = User({
            "username": "switch.operator",
            "dn": f"CN=Switch Operator,{ADMINISTRATIVE_OU_DN}",
            "groups": [],
        })
        save_user(self.user)
        with self.client.session_transaction() as session:
            session["_user_id"] = self.user.get_id()
            session["_fresh"] = True

    def tearDown(self):
        remove_user(self.user.get_id())

    def test_update_page_renders_required_fields_and_immediate_warning(self):
        switch = {
            "host": "SJC - SWITCH - SWTSJC-05",
            "ip": "192.0.2.21",
            "regional": "REGIONAL SAO JOSE DOS CAMPOS",
            "modelo": "HPE Networking Instant On 1930 48p",
            "status": "online",
        }
        with patch("web_config._resolver_switch_update", return_value=switch):
            response = self.client.get(
                "/switches/atualizar/SJC%20-%20SWITCH%20-%20SWTSJC-05"
            )

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Atualizar Switch", html)
        self.assertIn("REGIONAL SAO JOSE DOS CAMPOS", html)
        self.assertIn("HPE Networking Instant On 1930 48p", html)
        self.assertIn('id="switchUsername"', html)
        self.assertIn('id="switchPassword"', html)
        self.assertIn('id="switchFirmware"', html)
        self.assertIn('accept=".swi"', html)
        self.assertIn('id="switchScheduledAt"', html)
        self.assertIn("será realizado imediatamente", html)
        self.assertIn("Continuar", html)
        self.assertIn("Voltar", html)

    def test_global_csrf_token_is_accepted_by_firmware_api(self):
        token_response = self.client.get("/api/switches/firmware/csrf")
        self.assertEqual(token_response.status_code, 200)
        token = token_response.get_json()["csrf_token"]

        response = self.client.post(
            "/api/switches/SW-INEXISTENTE/firmware/preflight",
            headers={"X-CSRF-Token": token},
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("Switch nao encontrado", response.get_json()["message"])

    def test_update_page_denies_regional_support_without_operator_permission(self):
        remove_user(self.user.get_id())
        regional_user = User({
            "username": self.user.get_id(),
            "dn": (
                "CN=Regional Support,OU=Departamentos,OU=Bahia,"
                "OU=Regionais,DC=example,DC=local"
            ),
            "groups": [
                "CN=GGS_SUPORTE_BAHIA,OU=Grupos de Seguranca,"
                "OU=Grupos,DC=example,DC=local"
            ],
        })
        save_user(regional_user)

        response = self.client.get(
            "/switches/atualizar/SJC-SWITCH",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/switches"))

    def test_card_places_green_update_action_between_verify_and_edit(self):
        template = (Path(app.template_folder) / "switches.html").read_text(encoding="utf-8")
        verify_position = template.index("Verificar\n")
        update_position = template.index("url_for('atualizar_switch'")
        edit_position = template.index("onclick=\"editarSwitch")

        self.assertLess(verify_position, update_position)
        self.assertLess(update_position, edit_position)
        self.assertIn("btn-outline-success switch-icon-button", template)
        self.assertIn("bi-arrow-up-circle", template)
        self.assertIn("{% if sentinel_access.operator %}", template)

    def test_password_is_not_persisted_in_browser_storage(self):
        template = (Path(app.template_folder) / "atualizar_switch.html").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("localStorage", template)
        self.assertNotIn("sessionStorage", template)
        self.assertIn('autocomplete="current-password"', template)
        self.assertIn("passwordInput.value = '';", template)


if __name__ == "__main__":
    unittest.main()
