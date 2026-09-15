import unittest
from unittest.mock import patch
from pathlib import Path
from datetime import datetime

import web_config


class LinkFortimanagerStatusTest(unittest.TestCase):
    @patch.object(web_config.gerenciador_regionais, "salvar_regionais")
    @patch.object(web_config.gerenciador_regionais, "recarregar_regionais")
    def test_successful_sync_refreshes_timestamp_without_reporting_change(self, recarregar, salvar):
        link_anterior = {
            "id": "wan1",
            "nome": "WAN1",
            "categoria": "internet",
            "provedor": "OPERADORA TESTE",
            "ip": "187.1.1.1",
            "status": "online",
            "ultima_verificacao": "2026-08-28T08:05:15",
        }
        dados = {"regionais": {"REG_TESTE": {"links_internet_auto": [link_anterior]}}}

        with patch.object(web_config.gerenciador_regionais, "regionais", dados):
            alteradas = web_config._persistir_links_internet_exibicao_lote({
                "REG_TESTE": [{**link_anterior}],
            })

        novo_timestamp = dados["regionais"]["REG_TESTE"]["links_internet_auto"][0]["ultima_verificacao"]
        self.assertEqual([], alteradas)
        self.assertGreater(datetime.fromisoformat(novo_timestamp), datetime.fromisoformat("2026-08-28T08:05:15"))
        salvar.assert_called_once()

    def test_monitor_zabbix_packet_loss_above_ten_is_offline(self):
        sla_data = {"MONITOR_ZABBIX": {"packet_loss": 10.01}}
        status, source = web_config._resolve_link_operational_status("online", "active", sla_data)

        self.assertEqual("offline", status)
        self.assertEqual("monitor_zabbix_packet_loss", source)

    def test_monitor_zabbix_packet_loss_at_ten_is_online(self):
        sla_data = {"MONITOR_ZABBIX": {"packet-loss": "10%"}}
        status, source = web_config._resolve_link_operational_status("offline", "inactive", sla_data)

        self.assertEqual("online", status)
        self.assertEqual("monitor_zabbix_packet_loss", source)

    def test_monitor_zabbix_down_without_numeric_loss_is_offline(self):
        sla_data = {
            "Default_DNS": {"status": "down"},
            "MONITOR_ZABBIX": {"status": "down"},
        }

        status, source = web_config._resolve_link_operational_status("online", "inactive", sla_data)

        self.assertEqual(100.0, web_config._extract_monitor_zabbix_packet_loss(sla_data))
        self.assertEqual("offline", status)
        self.assertEqual("monitor_zabbix_packet_loss", source)

    @patch.object(web_config, "records_for")
    def test_regional_details_do_not_restore_link_removed_from_canonical_cache(self, records_for):
        records_for.return_value = [
            {"id": "wan1", "nome": "VIVO", "provedor": "VIVO", "ip": "186.1.1.1"},
            {"id": "wan2", "nome": "WCS", "provedor": "WCS", "ip": "187.1.1.1"},
        ]
        regional = {
            "links_internet_auto": [
                {
                    "id": "wan1",
                    "nome": "VIVO",
                    "provedor": "VIVO",
                    "ip": "186.1.1.1",
                    "categoria": "internet",
                },
            ]
        }

        links = web_config._obter_links_detalhe_regional("REG_TESTE", regional)

        self.assertEqual(["VIVO"], [link["nome"] for link in links])
        records_for.assert_not_called()

    def test_link_mode_is_fallback_when_monitor_zabbix_is_missing(self):
        status, source = web_config._resolve_link_operational_status("online", "inactive")

        self.assertEqual("online", status)
        self.assertEqual("link_mode", source)

    def test_sla_is_used_when_link_mode_is_unavailable(self):
        status, source = web_config._resolve_link_operational_status("", "inactive")

        self.assertEqual("offline", status)
        self.assertEqual("sla", source)

    @patch.object(web_config, "_list_fortimanager_devices")
    @patch.object(web_config, "_get_cached_fortimanager_device")
    def test_regional_cache_supplies_exact_device_name(self, cached_device, live_devices):
        live_devices.return_value = [{"name": "FGT_CONTROL_MCO", "ip": "10.0.0.99"}]
        cached_device.return_value = {
            "name": "FGT_CONTROL_MCO",
            "ip": "10.253.3.54",
            "status": "online",
        }
        regional = {"links": [{"fortigate_host": "10.253.3.54"}]}

        result = web_config._get_gerenciador_fortigate_regional("REG_CONTROL_MCO", regional)

        self.assertEqual("FGT_CONTROL_MCO", result["device"]["name"])
        self.assertEqual("10.253.3.54", result["device"]["ip"])

    def test_all_link_buttons_use_the_canonical_collection_routes(self):
        root = Path(__file__).parents[2]
        regionais = (root / "templates" / "regionais.html").read_text(encoding="utf-8")
        infraestrutura = (root / "templates" / "links_internet.html").read_text(encoding="utf-8")
        detalhes = (root / "templates" / "regional_detalhes.html").read_text(encoding="utf-8")
        backend = (root / "web_config.py").read_text(encoding="utf-8")

        self.assertIn("/api/regionais/verificar-links", regionais)
        self.assertIn("/api/links/verificar?async=1", infraestrutura)
        self.assertIn("/links/sincronizar", detalhes)
        self.assertIn("/link/${linkId}/testar", detalhes)
        self.assertIn("resultado = _executar_sincronizacao_links_todas_regionais()", backend)
        self.assertIn("resultado_coleta = _coletar_links_regional(", backend)


if __name__ == "__main__":
    unittest.main()
