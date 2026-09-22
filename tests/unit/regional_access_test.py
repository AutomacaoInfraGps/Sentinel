import unittest
import tempfile
from pathlib import Path

from regional_access import (
    access_scope,
    can_manage_regional_access,
    can_operate_sentinel,
    approve_group_mapping,
    dynamic_group_mapping,
    effective_user_groups,
    can_access_regional,
    filter_map_payload,
    filter_operational_payload,
    filter_records,
    normalize_group_name,
    has_sentinel_login_access,
    observe_support_groups,
    pending_group_suggestions,
)


class RegionalAccessTest(unittest.TestCase):
    def test_extracts_group_cn_from_ad_distinguished_name(self):
        self.assertEqual(
            normalize_group_name("CN=GGS_Suporte_RS,OU=Grupos de Seguranca,DC=Galaxia,DC=local"),
            "GGS_SUPORTE_RS",
        )

    def test_regional_groups_accumulate_scope(self):
        groups = ["CN=GGS_Suporte_RS,OU=Grupos,DC=Galaxia,DC=local", "GGS_Suporte_Loghis"]
        available = ["REG_TLSV_POA", "REG_LOGHIS", "REG_BAHIA"]
        scope = access_scope(groups, available)
        self.assertEqual(scope["allowed"], {"REG_TLSV_POA", "REG_LOGHIS"})
        self.assertTrue(can_access_regional(groups, "REG_TLSV POA", available))
        self.assertFalse(can_access_regional(groups, "REG_BAHIA", available))

    def test_corporate_group_sees_every_available_regional(self):
        scope = access_scope(["GGS_Suporte_Corporativo"], ["REG_A", "REG_B"])
        self.assertTrue(scope["corporate"])
        self.assertEqual(scope["allowed"], {"REG_A", "REG_B"})

    def test_builtin_remote_desktop_user_has_full_view_without_corporate_admin(self):
        scope = access_scope(
            ["CN=Remote Desktop Users,CN=Builtin,DC=Galaxia,DC=local"],
            ["REG_A", "REG_B"],
        )
        self.assertTrue(scope["full_view"])
        self.assertFalse(scope["corporate"])
        self.assertEqual(scope["allowed"], {"REG_A", "REG_B"})

    def test_account_operator_has_full_view_without_mapping_admin(self):
        groups = ["CN=Account Operators,CN=Builtin,DC=Galaxia,DC=local"]
        scope = access_scope(groups, ["REG_A", "REG_B"])
        self.assertTrue(scope["full_view"])
        self.assertFalse(scope["access_admin"])
        self.assertEqual(scope["allowed"], {"REG_A", "REG_B"})
        self.assertFalse(can_operate_sentinel(groups))
        self.assertEqual(
            filter_records([{"nome": "VPN órfã", "regional": ""}], groups),
            [{"nome": "VPN órfã", "regional": ""}],
        )

    def test_administrative_ou_marker_has_full_view(self):
        scope = access_scope(
            ["SENTINEL_ADMINISTRATIVE_OU"],
            ["REG_A", "REG_B"],
        )
        self.assertTrue(scope["full_view"])
        self.assertFalse(scope["access_admin"])
        self.assertEqual(scope["allowed"], {"REG_A", "REG_B"})
        self.assertTrue(can_operate_sentinel(["SENTINEL_ADMINISTRATIVE_OU"]))

    def test_administrative_ou_is_reapplied_from_distinguished_name(self):
        groups = effective_user_groups(
            ["CN=Remote Desktop Users,CN=Builtin,DC=Galaxia,DC=local"],
            (
                "CN=Roosevelt H D Andrade Pimentel,"
                "OU=Usuarios Administrativos,OU=Galaxia,DC=Galaxia,DC=local"
            ),
        )
        self.assertIn("SENTINEL_ADMINISTRATIVE_OU", groups)
        self.assertTrue(can_operate_sentinel(groups))

    def test_domain_admin_in_users_has_full_view_and_can_manage_mappings(self):
        groups = ["CN=Domain Admins,CN=Users,DC=Galaxia,DC=local"]
        scope = access_scope(groups, ["REG_A", "REG_B"])
        self.assertTrue(scope["full_view"])
        self.assertTrue(scope["access_admin"])
        self.assertTrue(can_manage_regional_access(groups))
        self.assertTrue(has_sentinel_login_access("chefe.adm", groups))

    def test_regional_support_group_can_login_without_full_view(self):
        groups = ["CN=GGS_Suporte_Bahia,OU=Grupos,DC=Galaxia,DC=local"]
        self.assertTrue(has_sentinel_login_access("suporte.bahia", groups))
        self.assertFalse(access_scope(groups, ["REG_BAHIA"])["full_view"])

    def test_operational_and_map_payloads_are_filtered(self):
        groups = ["GGS_Suporte_Bahia"]
        operational = {
            "groups": {"links": {"records": [
                {"regional": "REG_BAHIA", "nome": "WAN1"},
                {"regional": "REG_GOIAS", "nome": "WAN2"},
            ]}},
            "regionals": [{"codigo": "REG_BAHIA"}, {"codigo": "REG_GOIAS"}],
        }
        mapa = {
            "regionais": [
                {"codigo": "REG_BAHIA", "totais": {"links_online": 2}},
                {"codigo": "REG_GOIAS", "totais": {"links_online": 3}},
            ],
            "unmapped": {"vpns": [{"nome": "ORFA"}]},
        }
        filtered_operational = filter_operational_payload(operational, groups)
        filtered_map = filter_map_payload(mapa, groups)
        self.assertEqual(len(filtered_operational["groups"]["links"]["records"]), 1)
        self.assertEqual([item["codigo"] for item in filtered_map["regionais"]], ["REG_BAHIA"])
        self.assertEqual(filtered_map["unmapped"]["vpns"], [])
        self.assertEqual(filtered_map["resumo"]["links_online"], 2)

    def test_new_group_is_discovered_suggested_and_approved_without_code_change(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            discovery = Path(temp_dir) / "discovered.json"
            mappings = Path(temp_dir) / "mappings.json"
            group = "CN=GGS_Suporte_Nanuque,OU=Grupos,DC=Galaxia,DC=local"

            observe_support_groups([group], path=discovery)
            suggestions = pending_group_suggestions(
                ["REG_BAHIA", "REG_CONTROL_NANUNQUE"],
                path=discovery,
            )
            self.assertEqual(suggestions[0]["suggested_regional"], "REG_CONTROL_NANUNQUE")

            approve_group_mapping(
                "GGS_SUPORTE_NANUQUE",
                "REG_CONTROL_NANUNQUE",
                mappings_path=mappings,
                discovered_path=discovery,
            )
            self.assertEqual(
                dynamic_group_mapping(mappings)["GGS_SUPORTE_NANUQUE"],
                {"REG_CONTROL_NANUNQUE"},
            )
            scope = access_scope(
                ["GGS_SUPORTE_NANUQUE"],
                ["REG_BAHIA", "REG_CONTROL_NANUNQUE"],
                dynamic_path=mappings,
            )
            self.assertEqual(scope["allowed"], {"REG_CONTROL_NANUNQUE"})


if __name__ == "__main__":
    unittest.main()
