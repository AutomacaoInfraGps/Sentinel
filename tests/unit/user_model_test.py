import unittest

from user_model import User, get_user, remove_user, save_user


class UserModelTests(unittest.TestCase):
    def tearDown(self):
        remove_user("usuario.teste")

    def test_preserva_identidade_e_escopo_retornados_pelo_ad(self):
        user = User({
            "username": "usuario.teste",
            "display_name": "Usuario Teste",
            "email": "usuario.teste@empresa.local",
            "dn": "CN=Usuario Teste,OU=Suporte,DC=empresa,DC=local",
            "groups": [
                "CN=Sentinel-Suporte,OU=Grupos,DC=empresa,DC=local",
                "CN=Sentinel-Leitura,OU=Grupos,DC=empresa,DC=local",
            ],
        })

        save_user(user)
        loaded = get_user("usuario.teste")

        self.assertIs(loaded, user)
        self.assertTrue(loaded.is_authenticated)
        self.assertEqual(loaded.dn, "CN=Usuario Teste,OU=Suporte,DC=empresa,DC=local")
        self.assertEqual(len(loaded.groups), 2)

    def test_serializacao_preserva_dn_e_grupos(self):
        original = User({
            "username": "usuario.teste",
            "dn": "CN=Usuario Teste,OU=Suporte,DC=empresa,DC=local",
            "groups": ["CN=Sentinel-Suporte,DC=empresa,DC=local"],
        })

        restored = User.from_dict(original.to_dict())

        self.assertEqual(restored.dn, original.dn)
        self.assertEqual(restored.groups, original.groups)


if __name__ == "__main__":
    unittest.main()
