import unittest

from fluxo_neural import build_neural_flow_payload


class NeuralFlowPayloadTests(unittest.TestCase):
    def test_builds_device_topology_without_copying_sensitive_fields(self):
        payload = build_neural_flow_payload({
            "cache_status": "fresh",
            "fontes": {"atualizado_em": "2026-10-13T10:00:00"},
            "regionais": [{
                "codigo": "REG_BAHIA",
                "nome": "Regional Bahia",
                "uf": "BA",
                "senha": "nao-pode-sair",
                "servidores": [{
                    "nome": "SRV-BA-01",
                    "ip": "10.0.0.1",
                    "password": "segredo",
                }],
                "links": [{"nome": "Link principal", "api_key": "segredo-2"}],
                "switches": [],
                "firewalls": [{"hostname": "FW-BA", "modelo": "FortiGate-100F"}],
                "vpns": [{"tunel": "VPN_BAHIA"}],
                "aps": [{"name": "AP-RECEPCAO"}],
                "redes_wifi": [{
                    "nome": "SATURNO",
                    "rede": "VISITANTE (10)",
                    "ativo": True,
                    "x_passphrase": "tambem-nao-pode-sair",
                }],
            }],
        })

        self.assertEqual(payload["resumo"]["regionais"], 1)
        self.assertEqual(payload["resumo"]["dispositivos"], 6)
        self.assertEqual(payload["resumo"]["conexoes"], 6)
        self.assertEqual(payload["regionais"][0]["totais"]["servidores"], 1)
        self.assertEqual(
            {device["nome"] for device in payload["dispositivos"]},
            {"SRV-BA-01", "Link principal", "FortiGate-100F", "VPN_BAHIA", "AP-RECEPCAO", "SATURNO"},
        )
        serialized = repr(payload)
        self.assertNotIn("nao-pode-sair", serialized)
        self.assertNotIn("segredo", serialized)
        self.assertNotIn("password", serialized)
        self.assertNotIn("passphrase", serialized)
        server = next(
            device for device in payload["dispositivos"]
            if device["tipo"] == "servidores"
        )
        self.assertIn(
            {"rotulo": "IP", "valor": "10.0.0.1"},
            server["detalhes"],
        )

    def test_combines_link_interface_and_provider(self):
        payload = build_neural_flow_payload({
            "regionais": [{
                "codigo": "REG_BAHIA",
                "links": [{"nome": "WAN1", "provedor": "VIVO"}],
            }],
        })

        self.assertEqual(payload["dispositivos"][0]["nome"], "WAN1 - VIVO")

    def test_prefers_firewall_commercial_model(self):
        payload = build_neural_flow_payload({
            "regionais": [{
                "codigo": "REG_BAHIA",
                "firewalls": [{
                    "hostname": "FGT_REGBAHIA",
                    "descricao": "FortiGate-100F",
                }],
            }],
        })

        self.assertEqual(payload["dispositivos"][0]["nome"], "FortiGate-100F")


if __name__ == "__main__":
    unittest.main()
