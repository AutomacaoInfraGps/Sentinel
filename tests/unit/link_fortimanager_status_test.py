import unittest
from unittest.mock import patch
from pathlib import Path
from datetime import datetime

import web_config
from gerenciar_fortigate import GerenciadorFortigate, _parse_vpn_phase1_comments


class LinkFortimanagerStatusTest(unittest.TestCase):
    @patch.object(web_config, "snapshot_is_fresh", return_value=False)
    @patch.object(web_config, "load_operational_state")
    def test_stale_operational_group_never_reaches_pages(self, load_state, snapshot_fresh):
        load_state.return_value = {
            "groups": {
                "servidores": {
                    "updated_at": "2026-09-11T10:00:00",
                    "records": [{"nome": "OLD", "status": "offline", "regional": "REG_A"}],
                }
            }
        }

        self.assertEqual(web_config._fresh_operational_records("servidores"), [])

    @patch.object(web_config, "snapshot_is_fresh", return_value=True)
    @patch.object(web_config, "load_operational_state")
    def test_fresh_operational_group_is_filtered_by_regional(self, load_state, snapshot_fresh):
        load_state.return_value = {
            "groups": {
                "switches": {
                    "updated_at": "2026-09-16T10:00:00",
                    "records": [
                        {"nome": "SW-A", "regional": "REG_A"},
                        {"nome": "SW-B", "regional": "REG_B"},
                    ],
                }
            }
        }

        records = web_config._fresh_operational_records("switches", "reg_a")
        self.assertEqual(["SW-A"], [item["nome"] for item in records])

    def test_switch_groups_include_new_regionals_without_borrowing_devices(self):
        regionals = {
            "REG_CONTROL_ARAPIRACA": {
                "nome": "REG_CONTROL_ARAPIRACA",
                "descricao": "Regional Minas Gerais",
            },
            "REG_BELO_HORIZONTE": {
                "nome": "REG_BELO_HORIZONTE",
                "descricao": "Regional Minas Gerais",
            },
        }
        switches = [{
            "host": "SW-BH-01",
            "regional": "REGIONAL BELO HORIZONTE",
            "ip": "10.0.0.1",
        }]

        grouped = web_config._agrupar_switches_por_regionais_configuradas(switches, regionals)

        self.assertEqual([], grouped["REG_CONTROL_ARAPIRACA"])
        self.assertEqual(["SW-BH-01"], [item["host"] for item in grouped["REG_BELO_HORIZONTE"]])

    @patch.object(web_config.gerenciador_regionais, "obter_regional")
    @patch.object(web_config.gerenciador_regionais, "listar_regionais")
    @patch.object(web_config, "_fresh_operational_records")
    def test_regional_details_do_not_borrow_switches_when_snapshot_has_no_match(
        self, fresh_records, list_regionals, get_regional
    ):
        list_regionals.return_value = ["REG_CONTROL_ARAPIRACA", "REG_BELO_HORIZONTE"]
        get_regional.side_effect = lambda code: {"nome": code}
        fresh_records.return_value = [{
            "host": "SW-BH-01",
            "regional": "REG_BELO_HORIZONTE",
            "regional_zabbix": "REGIONAL BELO HORIZONTE",
        }]

        source, switches = web_config._obter_switches_detalhe_regional(
            "REG_CONTROL_ARAPIRACA",
            {"nome": "REG_CONTROL_ARAPIRACA", "descricao": "Regional Minas Gerais"},
        )

        self.assertEqual("REG_CONTROL_ARAPIRACA", source)
        self.assertEqual([], switches)

    def test_vpn_clear_filter_resets_search_and_notification_query(self):
        source = (Path(__file__).parents[2] / "templates" / "vpn_ipsec.html").read_text(encoding="utf-8")
        base_source = (Path(__file__).parents[2] / "templates" / "base.html").read_text(encoding="utf-8")
        self.assertIn("function limparFiltrosVpn()", source)
        self.assertIn("$('#vpnSearchInput').val('')", source)
        self.assertIn("clearNotificationSearchQuery()", source)
        self.assertIn("function clearNotificationSearchQuery()", base_source)
        self.assertIn("url.searchParams.delete('q')", base_source)
        self.assertIn("id=\"btnAtualizarVPN\"", source)

    def test_all_clear_filter_buttons_reset_search_and_notification_query(self):
        templates_root = Path(__file__).parents[2] / "templates"
        expected_handlers = {
            "regionais.html": "limparFiltrosRegionais",
            "antenas_simples.html": "limparFiltrosAntenas",
            "switches.html": "limparFiltrosSwitches",
            "vpn_ipsec.html": "limparFiltrosVpn",
            "emails_contatos.html": "limparFiltroEspecial",
        }

        for filename, handler in expected_handlers.items():
            with self.subTest(template=filename):
                source = (templates_root / filename).read_text(encoding="utf-8")
                self.assertIn(f"function {handler}()", source)
                self.assertIn("clearNotificationSearchQuery()", source)

    @patch.object(web_config, "publish_group_records")
    @patch.object(web_config, "_prepare_vpn_operational_records")
    @patch.object(web_config, "_obter_vpns_operacionais")
    def test_vpn_refresh_publishes_result_before_reload(
        self, fetch_vpns, prepare_records, publish_records
    ):
        fetch_vpns.return_value = {
            "success": True,
            "vpns": [{"tunel": "T001_TESTE", "status": "up"}],
            "source": "fortimanager_proxy",
        }
        prepare_records.return_value = [
            {"tunel": "T001_TESTE", "status": "online", "regional": "REG_TESTE"}
        ]

        previous_state = {
            "groups": {
                "vpns": {
                    "records": [{"tunel": "T001_TESTE", "regional": "SEM_REGIONAL"}]
                }
            }
        }
        with patch.object(web_config, "load_operational_state", return_value=previous_state), \
                patch.object(web_config.gerenciador_regionais, "recarregar_regionais") as reload_regionals:
            result = web_config._collect_and_publish_vpns()

        self.assertTrue(result["success"])
        self.assertEqual(result["total_atualizado"], 1)
        self.assertEqual(result["total_vinculado"], 1)
        self.assertEqual(result["novos_vinculos"], 1)
        self.assertEqual(result["total_sem_regional"], 0)
        self.assertEqual(result["source"], "fortimanager_proxy")
        reload_regionals.assert_called_once_with()
        publish_records.assert_called_once_with(
            "vpns", prepare_records.return_value, source="vpn_manual"
        )

    def test_vpn_refresh_relinks_orphan_after_regional_is_created(self):
        index = [{
            "chave": "REG_NOVAUNIDADE",
            "nome_exibicao": "NOVAUNIDADE",
            "tokens": web_config._gerar_tokens_regional("REG_NOVAUNIDADE"),
        }]
        stale_orphan = {
            "tunel": "T099_NOVAUNIDADE_01",
            "status": "online",
            "regional": "SEM_REGIONAL",
        }

        with patch.object(web_config, "_carregar_indice_regionais_vpn", return_value=index):
            records = web_config._prepare_vpn_operational_records([stale_orphan])

        self.assertEqual("REG_NOVAUNIDADE", records[0]["regional"])

    def test_control_regional_requires_the_specific_unit_name(self):
        devices = [
            {"name": "FGT_CTRLMACEIO", "hostname": "FGT_CTRLMACEIO", "ip": "10.0.0.1"},
            {"name": "FGT_CTRLNANUQUE", "hostname": "FGT_CTRLNANUQUE", "ip": "10.0.0.2"},
            {"name": "FGT_CTRLPONTENOVA", "hostname": "FGT_CTRLPONTENOVA", "ip": "10.0.0.3"},
        ]

        maceio = web_config._match_fortimanager_device(
            "REG_CONTROL_MACEIO", {"nome": "REG_CONTROL_MACEIO"}, devices
        )
        desconhecida = web_config._match_fortimanager_device(
            "REG_CONTROL_UNIDADE_NOVA", {"nome": "REG_CONTROL_UNIDADE_NOVA"}, devices
        )

        self.assertEqual("FGT_CTRLMACEIO", maceio["name"])
        self.assertEqual({}, desconhecida)

    def test_vpn_codes_map_ceara_units_and_control_nanuque_exactly(self):
        index = [
            {"chave": "REG_CEARA", "nome_exibicao": "CEARA", "tokens": web_config._gerar_tokens_regional("REG_CEARA")},
            {"chave": "REG_CEARA_2", "nome_exibicao": "CEARA 2", "tokens": web_config._gerar_tokens_regional("REG_CEARA_2")},
            {"chave": "REG_CONTROL_NANUQUE", "nome_exibicao": "CONTROL NANUQUE", "tokens": web_config._gerar_tokens_regional("REG_CONTROL_NANUQUE")},
            {"chave": "REG_CONTROL_MACEIO", "nome_exibicao": "CONTROL MACEIO", "tokens": web_config._gerar_tokens_regional("REG_CONTROL_MACEIO")},
        ]

        self.assertEqual("REG_CEARA", web_config._mapear_regional_vpn("CEARA", "T018", index)["chave"])
        self.assertEqual("REG_CEARA_2", web_config._mapear_regional_vpn("CEARA", "T024", index)["chave"])
        self.assertEqual("REG_CONTROL_NANUQUE", web_config._mapear_regional_vpn("NANUQUE", "T062", index)["chave"])
        self.assertEqual("REG_CONTROL_MACEIO", web_config._mapear_regional_vpn("MCO", "T060", index)["chave"])

    def test_fortigate_phase1_comments_are_parsed_by_tunnel(self):
        output = '''
config vpn ipsec phase1-interface
    edit "V070_MONCLAR04"
        set interface "WAN_MUNDIVOX"
        set comments "Regional CONTROL - MONTES CLAROS"
    next
    edit "T068_ARAPIRA04"
        set comments "Regional CONTROL - ARAPIRACA"
    next
end
'''

        comments = _parse_vpn_phase1_comments(output)

        self.assertEqual("Regional CONTROL - MONTES CLAROS", comments["V070_MONCLAR04"])
        self.assertEqual("Regional CONTROL - ARAPIRACA", comments["T068_ARAPIRA04"])

    @patch("gerenciar_fortigate.FortiManagerClient")
    def test_vpn_comments_are_loaded_from_manager_device_matching_fortigate_ip(self, client_class):
        manager = GerenciadorFortigate(
            host="10.254.12.1",
            username="admin",
            password="test",
        )
        client = client_class.return_value.__enter__.return_value
        client.list_devices.return_value = {
            "result": [{
                "data": [
                    {"name": "FGT_OUTRO", "ip": "10.0.0.1"},
                    {"name": "FTG_GLX_100F_MATRIZ", "ip": "10.254.12.1"},
                ],
            }],
        }
        client.get_vpn_phase1_comments.return_value = {
            "T001_PR_01": "REG_PARANA",
        }

        comments = manager._obter_comentarios_vpn_fortimanager()

        self.assertEqual(comments, {"T001_PR_01": "REG_PARANA"})
        client.get_vpn_phase1_comments.assert_called_once_with("FTG_GLX_100F_MATRIZ")

    def test_vpn_parana_is_linked_by_fortimanager_comment(self):
        index = [{
            "chave": "REG_PARANA",
            "nome_exibicao": "PARANA",
            "tokens": web_config._gerar_tokens_regional("REG_PARANA"),
            "identidades": {web_config._identidade_principal_regional("REG_PARANA")},
        }]

        with patch.object(web_config, "_carregar_indice_regionais_vpn", return_value=index):
            records = web_config._prepare_vpn_operational_records([{
                "tunel": "T001_PR_01",
                "comentario": "REG_PARANA",
                "status": "up",
            }])

        self.assertEqual(records[0]["regional"], "REG_PARANA")
        self.assertEqual(records[0]["vinculo_regional_origem"], "comentario")

    def test_vpn_comment_has_priority_and_tunnel_name_remains_fallback(self):
        regional_codes = ["REG_CONTROL_MONTESCLAROS", "REG_CONTROL_ARAPIRACA"]
        index = [
            {
                "chave": code,
                "nome_exibicao": code,
                "tokens": web_config._gerar_tokens_regional(code),
            }
            for code in regional_codes
        ]

        comment_match, comment_source = web_config._resolver_vinculo_regional_vpn({
            "tunel": "T068_ARAPIRA04",
            "comentario": "Regional CONTROL - MONTES CLAROS",
        }, index)
        fallback_match, fallback_source = web_config._resolver_vinculo_regional_vpn({
            "tunel": "T068_ARAPIRA04",
            "comentario": "",
        }, index)

        self.assertEqual("REG_CONTROL_MONTESCLAROS", comment_match["chave"])
        self.assertEqual("comentario", comment_source)
        self.assertEqual("REG_CONTROL_ARAPIRACA", fallback_match["chave"])
        self.assertEqual("tunel", fallback_source)

    def test_known_tunnel_code_resolves_ambiguous_regional_name(self):
        regional_codes = ["REG_SAO_LEOPOLDO", "REG_LEOPOLDO_B2"]
        index = [
            {
                "chave": code,
                "nome_exibicao": code,
                "tokens": web_config._gerar_tokens_regional(code),
                "identidades": {web_config._identidade_principal_regional(code)},
            }
            for code in regional_codes
        ]

        grouped = web_config._agrupar_vpns_por_regional([{
            "tunel": "T019_LEOPOLDO01",
            "comentario": "",
            "status": "up",
        }], index)

        self.assertIn("REG_SAO_LEOPOLDO", grouped["regionais"])
        self.assertEqual(grouped["vpns_por_regional"]["REG_SAO_LEOPOLDO"]["online"], 1)
        self.assertEqual(grouped["total_regionais"], 1)

    def test_known_tunnel_codes_map_without_fortimanager_comments(self):
        expected_by_tunnel = {
            "T001_PR_01": "REG_PARANA",
            "T019_LEOPOLDO01": "REG_SAO_LEOPOLDO",
            "T026_CMP1_01": "REG_CAMPINAS",
            "T028_CAM_B2_01": "REG_CAMPINAS_02",
            "T037_AMZ_01": "REG_AMAZONAS",
            "T046_RN_02": "REG_RIO_GRANDE_DO_NORTE",
            "T055_LC_01": "REG_GRSA_MACAE",
        }
        index = [
            {
                "chave": code,
                "nome_exibicao": code,
                "tokens": web_config._gerar_tokens_regional(code),
                "identidades": {web_config._identidade_principal_regional(code)},
            }
            for code in set(expected_by_tunnel.values())
        ]

        for tunnel, expected_regional in expected_by_tunnel.items():
            with self.subTest(tunnel=tunnel):
                match, source = web_config._resolver_vinculo_regional_vpn({
                    "tunel": tunnel,
                    "comentario": "",
                }, index)
                self.assertEqual(expected_regional, match["chave"])
                self.assertEqual("tunel", source)

    def test_vpn_name_variations_map_only_to_a_clear_unique_regional(self):
        regional_codes = [
            "REG_CONTROL_MONTESCLAROS",
            "REG_CONTROL_PONTENOVA",
            "REG_CONTROL_ARAPIRACA",
            "REG_CONTROL_NANUNQUE",
            "REG_CONTROL_OUROPRETO",
            "REG_CTRLPB",
            "REG_ORMEC_PARA",
            "REG_PARA",
        ]
        index = [
            {
                "chave": code,
                "nome_exibicao": code,
                "tokens": web_config._gerar_tokens_regional(code),
            }
            for code in regional_codes
        ]
        expected = {
            "MONCLAR": "REG_CONTROL_MONTESCLAROS",
            "PONTNOVA": "REG_CONTROL_PONTENOVA",
            "ARAPIRA": "REG_CONTROL_ARAPIRACA",
            "NANUQUE": "REG_CONTROL_NANUNQUE",
            "OUROPRET": "REG_CONTROL_OUROPRETO",
            "CRTLPB": "REG_CTRLPB",
            "PARA": "REG_PARA",
        }

        for vpn_name, regional_code in expected.items():
            with self.subTest(vpn_name=vpn_name):
                mapped = web_config._mapear_regional_vpn(vpn_name, "T999", index)
                self.assertIsNotNone(mapped)
                self.assertEqual(regional_code, mapped["chave"])

    @patch.object(web_config, "_get_cached_fortimanager_device")
    def test_control_inventory_overrides_contaminated_link_and_firewall_cache(self, cached_device):
        cached_device.return_value = {
            "name": "FGT_CTRLMACEIO", "hostname": "FGT_CTRLMACEIO", "ip": "10.0.0.1"
        }
        devices = [
            {"name": "FGT_CTRLMACEIO", "hostname": "FGT_CTRLMACEIO", "ip": "10.0.0.1"},
            {"name": "FGT_CTRLARAPIRACA", "hostname": "FGT_CTRLARAPIRACA", "ip": "10.0.0.2"},
        ]
        regional = {
            "nome": "REG_CONTROL_ARAPIRACA",
            "links_internet_auto": [{"fortigate_host": "10.0.0.1"}],
        }

        resolved = web_config._get_gerenciador_fortigate_regional(
            "REG_CONTROL_ARAPIRACA", regional, adom="root", fortimanager_devices=devices
        )

        self.assertEqual("FGT_CTRLARAPIRACA", resolved["device"]["name"])
        self.assertEqual("10.0.0.2", resolved["device"]["ip"])

    def test_unregistered_vpn_is_not_approximately_assigned_to_another_regional(self):
        index = [
            {"chave": "REG_ORMEC_PARA", "nome_exibicao": "ORMEC PARA", "tokens": web_config._gerar_tokens_regional("REG_ORMEC_PARA")},
        ]

        self.assertIsNone(web_config._mapear_regional_vpn("OUROPRETO", "T063", index))

        index.append({
            "chave": "REG_CONTROL_OURO_PRETO",
            "nome_exibicao": "CONTROL OURO PRETO",
            "tokens": web_config._gerar_tokens_regional("REG_CONTROL_OURO_PRETO"),
        })
        self.assertEqual(
            "REG_CONTROL_OURO_PRETO",
            web_config._mapear_regional_vpn("OUROPRETO", "T063", index)["chave"],
        )

    def test_firewalls_choose_single_most_specific_regional(self):
        regionals = {
            "REG_CEARA": {"nome": "REG_CEARA"},
            "REG_CEARA_2": {"nome": "REG_CEARA 2"},
            "REG_CONTROL_NANUQUE": {"nome": "REG_CONTROL_NANUQUE"},
            "REG_CONTROL_ARAPIRACA": {"nome": "REG_CONTROL_ARAPIRACA"},
        }

        self.assertEqual("REG_CEARA", web_config._resolver_regional_firewall("FGT_REGCEARA01", regionals))
        self.assertEqual("REG_CEARA_2", web_config._resolver_regional_firewall("FGT_REGCEARA02ULTRA", regionals))
        self.assertEqual("REG_CONTROL_NANUQUE", web_config._resolver_regional_firewall("FGT_CONTROL_NANUQUE", regionals))
        self.assertEqual("REG_CONTROL_ARAPIRACA", web_config._resolver_regional_firewall("FGT_REGCONTROL_ARAPIRACA", regionals))

    def test_firewalls_normalize_control_abbreviations_and_regional_prefix(self):
        regionals = {
            "REG_CONTROL_ARAPIRACA": {"nome": "REG_CONTROL_ARAPIRACA"},
            "REG_CONTROL_JANAUBA": {"nome": "REG_CONTROL_JANAUBA"},
            "REG_CONTROL_JANUARIA": {"nome": "REG_CONTROL_JANUARIA"},
            "REG_CONTROL_MONTESCLAROS": {"nome": "REG_CONTROL_MONTESCLAROS"},
            "REG_CONTROL_NANUNQUE": {"nome": "REG_CONTROL_NANUNQUE"},
            "REG_REGIONAL BELO HORIZONTE": {"nome": "REG_REGIONAL BELO HORIZONTE"},
        }

        self.assertEqual(
            "REG_CONTROL_ARAPIRACA",
            web_config._resolver_regional_firewall("FGT_CTRLARAPIRACA", regionals),
        )
        self.assertEqual(
            "REG_CONTROL_MONTESCLAROS",
            web_config._resolver_regional_firewall("FGT_CTRLMCLAROS", regionals),
        )
        self.assertEqual(
            "REG_CONTROL_NANUNQUE",
            web_config._resolver_regional_firewall("FGT_CTRLNANUQUE", regionals),
        )
        self.assertEqual(
            "REG_REGIONAL BELO HORIZONTE",
            web_config._resolver_regional_firewall("FGT_REGBELOHORIZONTE", regionals),
        )
        self.assertEqual(
            "REG_CONTROL_JANAUBA",
            web_config._resolver_regional_firewall("FGT_CTRLJANAUBA", regionals),
        )
        self.assertEqual(
            "REG_CONTROL_JANUARIA",
            web_config._resolver_regional_firewall("FGT_CTRLJANUARIA", regionals),
        )

    @patch.object(web_config, "_fresh_operational_records")
    def test_regional_details_remap_vpns_from_stale_snapshot(self, fresh_operational_records):
        fresh_operational_records.return_value = [
            {"tunel": "T024_CEARA2_01", "status": "online", "regional": "REG_CEARA"},
        ]
        index = [
            {"chave": "REG_CEARA", "nome_exibicao": "CEARA", "tokens": web_config._gerar_tokens_regional("REG_CEARA")},
            {"chave": "REG_CEARA_2", "nome_exibicao": "CEARA 2", "tokens": web_config._gerar_tokens_regional("REG_CEARA_2")},
        ]

        with patch.object(web_config, "_carregar_indice_regionais_vpn", return_value=index):
            vpns = web_config._obter_vpns_detalhe_regional("REG_CEARA_2")

        self.assertEqual(["T024_CEARA2_01"], [vpn["tunel"] for vpn in vpns])

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

    def test_monitor_zabbix_packet_loss_at_one_hundred_is_offline(self):
        sla_data = {"MONITOR_ZABBIX": {"packet_loss": 100}}
        status, source = web_config._resolve_link_operational_status("online", "active", sla_data)

        self.assertEqual("offline", status)
        self.assertEqual("monitor_zabbix_packet_loss", source)

    def test_monitor_zabbix_packet_loss_below_one_hundred_is_online(self):
        sla_data = {"MONITOR_ZABBIX": {"packet-loss": "99.99%"}}
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

    @patch.object(web_config, "_fresh_operational_records")
    def test_regional_details_do_not_restore_link_removed_from_canonical_cache(self, operational_records):
        operational_records.return_value = [
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
        operational_records.assert_not_called()

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
    def test_live_inventory_refreshes_ip_for_cached_device_name(self, cached_device, live_devices):
        live_devices.return_value = [{"name": "FGT_CONTROL_MCO", "ip": "10.0.0.99"}]
        cached_device.return_value = {
            "name": "FGT_CONTROL_MCO",
            "ip": "10.253.3.54",
            "status": "online",
        }
        regional = {"links": [{"fortigate_host": "10.253.3.54"}]}

        result = web_config._get_gerenciador_fortigate_regional("REG_CONTROL_MCO", regional)

        self.assertEqual("FGT_CONTROL_MCO", result["device"]["name"])
        self.assertEqual("10.0.0.99", result["device"]["ip"])

    def test_public_sdwan_interface_can_use_legacy_dmz_or_ha_name(self):
        interface = {
            "name": "dmz",
            "alias": "(WAN_VIVO)",
            "ip": "201.63.46.74 255.255.255.248",
            "role": 1,
            "status": True,
        }

        self.assertTrue(web_config._is_wan_interface(interface))
        normalized = {
            "interface_monitorada": "dmz",
            "provedor": "(WAN_VIVO)",
            "ip": "201.63.46.74",
            "categoria": "internet",
            "regra_origem": "links_internet_auto",
        }
        self.assertTrue(web_config._should_keep_synced_link(normalized))
        self.assertTrue(web_config._is_internet_link_candidate(normalized))

    @patch.object(web_config, "_get_cached_fortimanager_device", return_value={})
    def test_live_inventory_resolves_device_despite_stale_link_ip(self, cached_device):
        regional = {
            "nome": "REG_NUTRICAR",
            "links": [{"nome": "WAN1", "fortigate_host": "10.253.2.146"}],
        }
        devices = [{"name": "FGT_NUTRICAR", "hostname": "FGT_NUTRICAR", "ip": "10.253.2.144"}]

        result = web_config._get_gerenciador_fortigate_regional(
            "REG_NUTRICAR",
            regional,
            adom="GPS_UNIDADES-70",
            fortimanager_devices=devices,
        )

        self.assertEqual("FGT_NUTRICAR", result["device"]["name"])
        self.assertEqual("10.253.2.144", result["device"]["ip"])

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

    def test_fortimanager_warning_uses_error_overlay(self):
        detalhes = (Path(__file__).parents[2] / "templates" / "regional_detalhes.html").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "falharOverlayAcaoRegional('FortiManager indisponível', data.message",
            detalhes,
        )
        self.assertIn(
            "falharOverlayAcaoRegional('FortiManager indisponível', message",
            detalhes,
        )


if __name__ == "__main__":
    unittest.main()
