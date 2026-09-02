import re
import unittest
import unicodedata

from regional_matching import find_regional_code


def normalize(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).upper()
    text = re.sub(r"[^A-Z0-9]+", "_", text).strip("_")
    if text.startswith("REG_"):
        text = text[4:]
    text = text.replace("REGIONAL_", "")
    return text.strip("_")


class RegionalMatchingTests(unittest.TestCase):
    def setUp(self):
        self.regionals = {
            "REG_MACAE": {"nome": "REG_MACAE", "descricao": "Regional Macaé"},
            "REG_GRSA_MACAE": {"nome": "REG_GRSA_MACAE"},
        }

    def test_regional_macae_permanece_separada(self):
        code = find_regional_code(self.regionals, normalize("REGIONAL MACAE"), normalize)
        self.assertEqual(code, "REG_MACAE")

    def test_regional_grsa_macae_permanece_separada(self):
        code = find_regional_code(self.regionals, normalize("REGIONAL GRSA MACAE"), normalize)
        self.assertEqual(code, "REG_GRSA_MACAE")


if __name__ == "__main__":
    unittest.main()
