import unittest
from io import BytesIO

from openpyxl import load_workbook

from fluxo_neural import (
    build_neural_export_rows,
    build_neural_flow_payload,
    build_neural_xlsx,
)


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
                    "sistema_operacional": "Windows Server",
                    "porta": 3389,
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
        self.assertIn(
            {"rotulo": "Sistema operacional", "valor": "Windows Server"},
            server["detalhes"],
        )
        self.assertIn(
            {"rotulo": "Porta", "valor": "3389"},
            server["detalhes"],
        )

    def test_combines_link_interface_and_provider(self):
        payload = build_neural_flow_payload({
            "regionais": [{
                "codigo": "REG_BAHIA",
                "links": [{
                    "nome": "WAN1",
                    "provedor": "VIVO",
                    "velocidade": "500 Mbps",
                    "packet_loss_percent": 0.2,
                }],
            }],
        })

        self.assertEqual(payload["dispositivos"][0]["nome"], "WAN1 - VIVO")
        self.assertIn(
            {"rotulo": "Velocidade", "valor": "500 Mbps"},
            payload["dispositivos"][0]["detalhes"],
        )
        self.assertIn(
            {"rotulo": "Perda de pacotes", "valor": "0.2"},
            payload["dispositivos"][0]["detalhes"],
        )

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

    def test_export_rows_follow_regional_type_and_text_filters(self):
        payload = build_neural_flow_payload({
            "regionais": [
                {
                    "codigo": "REG_BAHIA",
                    "nome": "Bahia",
                    "uf": "BA",
                    "servidores": [{"nome": "Sirius", "ip": "10.0.0.10"}],
                    "links": [{"nome": "WAN1", "provedor": "VIVO"}],
                },
                {
                    "codigo": "REG_GOIAS",
                    "nome": "Goias",
                    "uf": "GO",
                    "servidores": [{"nome": "Rigel", "ip": "10.0.1.10"}],
                },
            ],
        })

        rows = build_neural_export_rows(
            payload,
            regional_id="REG_BAHIA",
            device_type="servidores",
            query="sirius",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Regional"], "Bahia")
        self.assertEqual(rows[0]["Categoria"], "Servidor")
        self.assertEqual(rows[0]["Dispositivo"], "Sirius")
        self.assertEqual(rows[0]["IP"], "10.0.0.10")

    def test_xlsx_is_valid_and_neutralizes_formula_cells(self):
        content = build_neural_xlsx([{
            "Regional": "Bahia",
            "Codigo": "REG_BAHIA",
            "Dispositivo": "=HYPERLINK(\"https://example.invalid\")",
        }])
        workbook = load_workbook(BytesIO(content), data_only=False)
        worksheet = workbook["Fluxo Neural"]

        self.assertEqual(worksheet["A2"].value, "Bahia")
        self.assertEqual(worksheet["B2"].value, "REG_BAHIA")
        self.assertTrue(worksheet["G2"].value.startswith("'="))
        self.assertEqual(worksheet.freeze_panes, "A2")
        self.assertFalse(worksheet.sheet_view.showGridLines)

    def test_xlsx_keeps_each_device_in_one_row_with_details_as_columns(self):
        rows = [{
            "Regional": "Bahia",
            "Codigo": "REG_BAHIA",
            "Categoria": "Servidor",
            "Dispositivo": "Acrab",
            "IP": "10.254.13.10",
            "Funcao": "API",
            "Modelo": "VMware",
            "Porta": "443",
        }]

        workbook = load_workbook(BytesIO(build_neural_xlsx(rows)))
        worksheet = workbook["Fluxo Neural"]
        headers = [cell.value for cell in worksheet[1]]

        self.assertEqual(worksheet.max_row, 2)
        self.assertEqual(worksheet.cell(2, headers.index("Dispositivo") + 1).value, "Acrab")
        self.assertEqual(worksheet.cell(2, headers.index("IP") + 1).value, "10.254.13.10")
        self.assertEqual(worksheet.cell(2, headers.index("Funcao") + 1).value, "API")
        self.assertEqual(worksheet.cell(2, headers.index("Porta") + 1).value, "443")

    def test_export_keeps_every_device_category_in_a_single_row(self):
        payload = build_neural_flow_payload({
            "regionais": [{
                "codigo": "REG_BAHIA",
                "nome": "Bahia",
                "servidores": [{"nome": "Acrab", "ip": "10.0.0.1", "modelo": "VMware"}],
                "switches": [{"host": "SW-BA-01", "ip": "10.0.0.2", "firmware": "1.2"}],
                "links": [{"nome": "WAN1", "provedor": "VIVO", "velocidade": "500 Mbps"}],
                "firewalls": [{"hostname": "FGT-BA", "modelo": "FortiGate-100F", "firmware": "7.4"}],
                "vpns": [{"tunel": "VPN-BA", "remote_ip": "192.0.2.1", "status": "online"}],
                "aps": [{"nome": "AP-BA-01", "ip": "10.0.0.3", "clientes": 12}],
                "redes_wifi": [{"nome": "MARTE", "rede": "USUARIOS", "bandas": ["5 GHz"]}],
            }],
        })

        rows = build_neural_export_rows(payload)

        self.assertEqual(len(rows), 7)
        self.assertEqual(len({row["Dispositivo"] for row in rows}), 7)
        self.assertEqual(next(row for row in rows if row["Categoria"] == "Switch")["Firmware"], "1.2")
        self.assertEqual(next(row for row in rows if row["Categoria"] == "Firewall")["Modelo"], "FortiGate-100F")
        self.assertEqual(next(row for row in rows if row["Categoria"] == "VPN")["IP remoto"], "192.0.2.1")
        self.assertEqual(next(row for row in rows if row["Categoria"] == "Antena UniFi")["Clientes"], "12")
        self.assertEqual(next(row for row in rows if row["Categoria"] == "Rede Wi-Fi")["Bandas"], "5 GHz")


if __name__ == "__main__":
    unittest.main()
