import unittest
from unittest.mock import patch

from user_model import User, remove_user, save_user
from security_hardening import is_safe_next_url
from web_config import app


class SecurityHTTPTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()
        self.user_ids = []

    def tearDown(self):
        for user_id in self.user_ids:
            remove_user(user_id)

    def _login_session(self, username, groups, dn="CN=Teste,DC=Galaxia,DC=local"):
        user = User({
            "username": username,
            "display_name": username,
            "dn": dn,
            "groups": groups,
        })
        save_user(user)
        self.user_ids.append(username)
        with self.client.session_transaction() as session:
            session["_user_id"] = username
            session["_fresh"] = True
            session["_csrf_token"] = "test-csrf-token"

    def test_anonymous_api_is_rejected_before_route_execution(self):
        response = self.client.post("/api/regional", json={})
        self.assertEqual(response.status_code, 401)

    def test_anonymous_page_redirects_to_login(self):
        response = self.client.get("/regionais")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login?next=", response.headers["Location"])

    def test_login_form_and_security_headers_are_present(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="csrf_token"', response.data)
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "SAMEORIGIN")
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])

    def test_unsafe_request_without_csrf_is_rejected(self):
        self._login_session("admin.csrf", ["SENTINEL_ADMINISTRATIVE_OU"])
        response = self.client.post("/api/regional", json={})
        self.assertEqual(response.status_code, 400)

    def test_same_origin_header_does_not_replace_csrf_token(self):
        self._login_session("admin.origin", ["SENTINEL_ADMINISTRATIVE_OU"])
        response = self.client.post(
            "/api/regional",
            json={},
            headers={"Origin": "http://localhost"},
        )
        self.assertEqual(response.status_code, 400)

    def test_valid_csrf_token_allows_logout(self):
        self._login_session("admin.logout", ["SENTINEL_ADMINISTRATIVE_OU"])
        response = self.client.post(
            "/logout",
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/login"))

    def test_view_only_user_cannot_enumerate_routes(self):
        self._login_session(
            "viewer.test",
            ["CN=Remote Desktop Users,CN=Builtin,DC=Galaxia,DC=local"],
        )
        response = self.client.get("/api/rotas")
        self.assertEqual(response.status_code, 403)

    def test_administrative_ou_can_access_operator_endpoint(self):
        self._login_session("admin.operator", ["SENTINEL_ADMINISTRATIVE_OU"])
        response = self.client.get("/api/rotas")
        self.assertEqual(response.status_code, 200)

    def test_administrative_ou_dn_restores_operator_access_in_current_request(self):
        self._login_session(
            "admin.dn",
            ["CN=Remote Desktop Users,CN=Builtin,DC=Galaxia,DC=local"],
            (
                "CN=Administrador,OU=Usuarios Administrativos,"
                "OU=Galaxia,DC=Galaxia,DC=local"
            ),
        )
        response = self.client.get("/api/rotas")
        self.assertEqual(response.status_code, 200)

    def test_external_next_url_is_rejected(self):
        with app.test_request_context("/login", base_url="http://sentinel.local"):
            self.assertFalse(is_safe_next_url("https://example.org/roubo"))
            self.assertTrue(is_safe_next_url("/regionais"))

    def test_regional_user_cannot_open_another_regional_directly(self):
        self._login_session("suporte.bahia", ["GGS_SUPORTE_BAHIA"])
        with patch.object(
            __import__("web_config").gerenciador_regionais,
            "listar_regionais",
            return_value=["REG_BAHIA", "REG_GOIAS"],
        ):
            response = self.client.get("/regional/REG_GOIAS")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b">Backup<", response.data)

    def test_view_only_user_cannot_open_management_form(self):
        self._login_session(
            "viewer.management",
            ["CN=Remote Desktop Users,CN=Builtin,DC=Galaxia,DC=local"],
        )
        response = self.client.get("/switches/cadastrar")
        self.assertEqual(response.status_code, 403)

    def test_authenticated_response_disables_browser_cache(self):
        self._login_session("admin.cache", ["SENTINEL_ADMINISTRATIVE_OU"])
        response = self.client.get("/api/rotas")
        self.assertEqual(response.headers["Cache-Control"], "no-store, max-age=0")


if __name__ == "__main__":
    unittest.main()
