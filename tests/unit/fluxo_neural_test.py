import unittest

from fluxo_neural import build_neural_flow_payload


class NeuralFlowPayloadTests(unittest.TestCase):
    def test_builds_aggregate_graph_without_copying_sensitive_fields(self):
        payload = build_neural_flow_payload({
            "cache_status": "fresh",
            "fontes": {"atualizado_em": "2026-10-13T10:00:00"},
            "regionais": [{
                "codigo": "REG_TESTE",
                "nome": "Regional Teste",
                "uf": "SP",
                "senha": "nao-pode-sair",
                "servidores": [{"ip": "10.0.0.1", "password": "segredo"}],
                "totais": {
                    "servidores_online": 2,
                    "servidores_offline": 1,
                    "vpns_online": 1,
                    "links_online": 2,
                    "firewalls_ok": 3,
                    "firewalls_warning": 1,
                    "firewalls_alerta": 2,
                },
            }],
        })

        self.assertEqual(payload["resumo"]["regionais"], 1)
        self.assertEqual(payload["resumo"]["conexoes"], 3)
        self.assertEqual(payload["regionais"][0]["status"], "alert")
        self.assertEqual(payload["regionais"][0]["alertas"], 3)
        self.assertEqual(payload["regionais"][0]["totais"]["firewalls"]["total"], 5)
        serialized = repr(payload)
        self.assertNotIn("nao-pode-sair", serialized)
        self.assertNotIn("10.0.0.1", serialized)
        self.assertNotIn("segredo", serialized)


if __name__ == "__main__":
    unittest.main()
