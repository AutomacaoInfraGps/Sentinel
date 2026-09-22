import unittest
from unittest.mock import patch

import json
import subprocess

from auth_ad import AuthAD
from regional_access import access_scope


class AuthADAccessTest(unittest.TestCase):
    def _auth(self, user_data):
        auth = object.__new__(AuthAD)
        auth.server_ip = "127.0.0.1"
        auth.domain = "GALAXIA.LOCAL"
        auth.domain_netbios = "GALAXIA"
        auth.dc_server = "SIRIUS"
        auth.ou_autorizada = "OU=Usuarios Administrativos,OU=Galaxia,DC=Galaxia,DC=local"
        auth._buscar_dados_usuario_powershell = lambda username, password: user_data
        return auth

    def test_administrative_ou_grants_full_view_without_user_exception(self):
        auth = self._auth({
            "username": "admin.pimentel",
            "display_name": "Roosevelt",
            "email": "",
            "dn": (
                "CN=Roosevelt H D Andrade Pimentel,"
                "OU=Usuarios Administrativos,OU=Galaxia,DC=Galaxia,DC=local"
            ),
            "groups": [],
        })

        success, user_data, _ = auth.autenticar_usuario("admin.pimentel", "senha")

        self.assertTrue(success)
        self.assertIn("SENTINEL_ADMINISTRATIVE_OU", user_data["groups"])
        self.assertTrue(access_scope(user_data["groups"], ["REG_A"])["full_view"])

    def test_failed_permission_lookup_does_not_create_administrative_access(self):
        auth = self._auth(None)

        success, user_data, message = auth.autenticar_usuario("usuario", "senha")

        self.assertFalse(success)
        self.assertIsNone(user_data)
        self.assertEqual(message, "Usuário ou senha inválidos")

    def test_native_ad_lookup_authorizes_administrative_ou(self):
        auth = self._auth(None)
        auth._buscar_dados_usuario_powershell = lambda username, password: {
            "username": username,
            "display_name": "Administrador",
            "email": "",
            "dn": (
                "CN=Administrador,OU=Usuarios Administrativos,"
                "OU=Galaxia,DC=Galaxia,DC=local"
            ),
            "groups": [],
        }

        success, user_data, _ = auth.autenticar_usuario("admin.teste", "senha")

        self.assertTrue(success)
        self.assertIn("SENTINEL_ADMINISTRATIVE_OU", user_data["groups"])

    @patch("auth_ad.subprocess.run")
    def test_native_lookup_uses_upn_and_keeps_password_out_of_command(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({
                "username": "admin.pimentel",
                "display_name": "Roosevelt",
                "email": "",
                "dn": (
                    "CN=Roosevelt,OU=Usuarios Administrativos,"
                    "OU=Galaxia,DC=Galaxia,DC=local"
                ),
                "groups": [],
            }),
            stderr="",
        )
        auth = object.__new__(AuthAD)
        auth.domain = "GALAXIA.LOCAL"
        auth.domain_netbios = "GALAXIA"
        auth.dc_server = "SIRIUS"

        result = auth._buscar_dados_usuario_powershell("admin.pimentel", "segredo")

        self.assertIsNotNone(result)
        command = run.call_args.args[0]
        options = run.call_args.kwargs
        self.assertNotIn("segredo", " ".join(command))
        self.assertEqual(options["input"], "segredo")
        self.assertEqual(options["env"]["SENTINEL_AD_DOMAIN"], "GALAXIA.LOCAL")
        self.assertIn("'@'", command[-1])


if __name__ == "__main__":
    unittest.main()
