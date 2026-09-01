import unittest

from services.unifi_models import UNIFI_MODEL_NAMES, nome_modelo_unifi, normalizar_modelo_ap


class UnifiModelsTest(unittest.TestCase):
    def test_modelos_conhecidos(self):
        esperados = {
            "UAL6": "U6 LITE",
            "U7PG2": "AC PRO",
            "U7HD": "AC HD",
            "UALR6v2": "U6 LR",
            "UAP6MP": "U6 PRO",
            "U7LR": "AC LR",
            "U7MP": "AC Mesh PRO",
            "U6MP": "U6 Mesh PRO",
            "U7LT": "AC LITE",
            "BZ2LR": "UAP LR",
            "BZ2": "UAP",
            "U7PRO": "U7 PRO",
            "U7PROMAX": "U7 PRO MAX",
            "UKPW": "U7 Outdoor",
            "UAPA693": "U7 Lite",
            "U7SHD": "AC SHD",
        }
        self.assertEqual(len(UNIFI_MODEL_NAMES), len(esperados))
        for codigo, nome in esperados.items():
            with self.subTest(codigo=codigo):
                self.assertEqual(nome_modelo_unifi(codigo), nome)

    def test_codigo_desconhecido_e_preservado(self):
        self.assertEqual(nome_modelo_unifi("MODELO_NOVO"), "MODELO_NOVO")
        self.assertEqual(nome_modelo_unifi(None), "")

    def test_cache_operacional_antigo_e_normalizado_sem_alterar_original(self):
        antigo = {"nome": "AP TESTE", "modelo_codigo": "UAP6MP", "modelo": "UAP6MP"}
        normalizado = normalizar_modelo_ap(antigo)
        self.assertEqual(normalizado["modelo"], "U6 PRO")
        self.assertEqual(antigo["modelo"], "UAP6MP")


if __name__ == "__main__":
    unittest.main()
