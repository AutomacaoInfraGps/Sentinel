"""Exercise page aggregation without starting the production app or collectors."""

import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from regional_access import normalize_regional_code


def load_page_functions(namespace):
    path = Path(__file__).resolve().parents[2] / "web_config.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {"_coletar_links_multiregional", "_ordenar_regionais_links", "listar_links"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    for node in nodes:
        node.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class LinksPageLoadingTests(unittest.TestCase):
    def setUp(self):
        self.regionals = {
            f"REG_{index}": {"nome": f"Regional {index}", "links_internet_auto": [
                {"nome": "WAN1", "status": "online"},
                {"nome": "WAN2", "status": "offline"},
            ]} for index in range(51)
        }
        self.manager = SimpleNamespace(
            recarregar_regionais=Mock(side_effect=lambda: {"regionais": self.regionals}),
            listar_regionais=Mock(side_effect=AssertionError("unnecessary full reload")),
            obter_regional=Mock(side_effect=AssertionError("unnecessary per-regional reload")),
        )
        self.scope = Mock(return_value={"allowed": {"REG_0"}})
        self.render = Mock(side_effect=lambda template, **context: context)
        self.flash = Mock()
        self.ns = load_page_functions({
            "datetime": datetime, "gerenciador_regionais": self.manager,
            "_obter_links_internet_exibicao": lambda regional: regional.get("links_internet_auto", []),
            "_preparar_link_para_template": dict,
            "_formatar_nome_link_dashboard": lambda link: link["nome"],
            "_ordenar_links_internet": lambda links: sorted(links, key=lambda link: link["nome"]),
            "_current_access_scope": self.scope,
            "normalize_regional_code": normalize_regional_code,
            "render_template": self.render, "flash": self.flash,
        })

    def test_51_regionals_use_one_load_and_keep_saved_statuses(self):
        result = self.ns["_coletar_links_multiregional"]()
        self.manager.recarregar_regionais.assert_called_once_with()
        self.manager.listar_regionais.assert_not_called()
        self.manager.obter_regional.assert_not_called()
        self.assertEqual(result["resumo"]["total_regionais"], 51)
        self.assertEqual(result["resumo"]["total_links"], 102)
        self.assertEqual(result["resumo"]["links_online"], 51)
        self.assertEqual(result["resumo"]["links_offline"], 51)
        self.assertNotIn("codigo_regional", self.regionals["REG_0"]["links_internet_auto"][0])

    def test_later_request_reads_new_saved_status(self):
        self.ns["_coletar_links_multiregional"]()
        self.regionals["REG_0"]["links_internet_auto"][0]["status"] = "offline"
        result = self.ns["_coletar_links_multiregional"]()
        self.assertEqual(result["resumo"]["links_offline"], 52)
        self.assertEqual(self.manager.recarregar_regionais.call_count, 2)

    def test_page_calculates_scope_once_and_filters_all_outputs(self):
        result = self.ns["listar_links"]()
        self.scope.assert_called_once_with()
        self.flash.assert_not_called()
        self.assertEqual(len(result["links"]), 2)
        self.assertEqual(set(result["links_por_regional"]), {"REGIONAL 0"})
        self.assertTrue(all(link["codigo_regional"] == "REG_0" for link in result["links"]))
        self.assertEqual(result["resumo_links"]["total_regionais"], 1)
        self.assertEqual(result["resumo_links"]["total_links"], 2)

    def test_empty_scope_reveals_no_links(self):
        self.scope.return_value = {"allowed": set()}
        result = self.ns["listar_links"]()
        self.assertEqual(result["links"], [])
        self.assertEqual(result["links_por_regional"], {})
        self.assertEqual(result["resumo_links"]["total_links"], 0)

    def test_scope_is_not_reused_for_another_request(self):
        self.ns["listar_links"]()
        self.scope.return_value = {"allowed": {"REG_1"}}
        result = self.ns["listar_links"]()
        self.assertEqual(set(result["links_por_regional"]), {"REGIONAL 1"})
        self.assertEqual(self.scope.call_count, 2)

    def test_sdwan_uses_same_scope_and_normalization(self):
        self.ns["_coletar_links_multiregional"] = lambda: {
            "success": True, "links": [], "links_por_regional": {},
            "sd_wan_por_regional": {"reg-0": {"state": "ok"}, "REG_1": {"state": "offline"}},
        }
        result = self.ns["listar_links"]()
        self.assertEqual(result["sd_wan_por_regional"], {"reg-0": {"state": "ok"}})


if __name__ == "__main__":
    unittest.main()
