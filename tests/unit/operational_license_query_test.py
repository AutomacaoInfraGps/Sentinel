from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import MagicMock

from services.operational_license_query import LicenseQueryError, query_postgres_licenses


NOW = datetime(2026, 11, 16, 11, 5, tzinfo=timezone.utc)


def license_row(code="REG_TLSV_POA", days=35, *, known=True, unavailable=False,
                previous=False, serial="FW1", expired=False):
    return (code, "Firewall", serial, "forticare", "valid",
            NOW + timedelta(days=35) if known else None, None, days, NOW,
            unavailable, expired, False, previous, NOW if previous else None)


def connection(rows=(), *, marker=NOW, missing_details=0):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [("sentinel", 5433), (marker,) if marker else None,
                                   (missing_details,)]
    cursor.fetchall.return_value = list(rows)
    return conn, cursor


class LicenseQueryTest(unittest.TestCase):
    def test_scoped_sql_parameter_and_read_only(self):
        conn, cursor = connection([license_row()])
        result = query_postgres_licenses(conn, allowed_regionals=["REG_TLSV_POA"], now=NOW)
        sql, params = cursor.execute.call_args.args
        self.assertIn("f.codigo_regional = ANY(%s)", sql)
        self.assertIn("f.presente_no_snapshot AND l.presente_no_snapshot", sql)
        self.assertEqual(params, (["REG_TLSV_POA"],))
        self.assertIn("READ ONLY", cursor.execute.call_args_list[0].args[0])
        self.assertEqual(result["summary"]["records"], 1)
        self.assertTrue(result["fresh"])
        self.assertEqual(result["records"][0]["days_remaining"], 35)

    def test_filters_complete_source_before_pagination(self):
        rows = [license_row(days=200, serial=f"FW{i}") for i in range(25)]
        rows += [license_row(days=day, serial=f"MATCH{day}") for day in (50, 0, 35)]
        conn, _ = connection(rows)
        result = query_postgres_licenses(conn, allowed_regionals=["REG_TLSV_POA"],
                                         expires_within_days=50, limit=2, now=NOW)
        self.assertEqual(result["summary"]["records"], 3)
        self.assertEqual([r["days_remaining"] for r in result["records"]], [0, 35])
        self.assertEqual(result["next_offset"], 2)
        conn, _ = connection(rows)
        page = query_postgres_licenses(conn, allowed_regionals=["REG_TLSV_POA"],
                                       expires_within_days=50, offset=2, limit=2, now=NOW)
        self.assertEqual(page["summary"]["records"], 3)
        self.assertEqual(page["records"][0]["days_remaining"], 50)
        self.assertIsNone(page["next_offset"])

    def test_unknown_unavailable_negative_not_zero(self):
        conn, _ = connection([license_row(days=0, known=False),
                              license_row(days=2, unavailable=True),
                              license_row(days=-1), license_row(days=0)])
        result = query_postgres_licenses(conn, allowed_regionals=["REG_TLSV_POA"],
                                         expires_within_days=50, now=NOW)
        self.assertEqual(result["summary"]["records"], 1)
        self.assertEqual(result["data_gaps"]["days_remaining_unavailable"], 2)
        self.assertFalse(result["fresh"])

    def test_previous_data_disclosed_and_stale_marker(self):
        conn, _ = connection([license_row(previous=True)], marker=NOW - timedelta(hours=1))
        result = query_postgres_licenses(conn, allowed_regionals=["REG_TLSV_POA"], now=NOW)
        self.assertTrue(result["records"][0]["previous_data"])
        self.assertEqual(result["data_gaps"]["previous_data"], 1)
        self.assertFalse(result["fresh"])

    def test_empty_scope_never_queries_database(self):
        conn, _ = connection()
        result = query_postgres_licenses(conn, allowed_regionals=[], now=NOW)
        conn.cursor.assert_not_called()
        self.assertEqual(result["summary"]["records"], 0)

    def test_missing_license_details_not_a_complete_zero_answer(self):
        conn, _ = connection(missing_details=1)
        result = query_postgres_licenses(conn, allowed_regionals=["REG_TLSV_POA"], now=NOW)
        self.assertEqual(result["summary"]["records"], 0)
        self.assertEqual(result["data_gaps"]["firewalls_without_license_details"], 1)
        self.assertFalse(result["fresh"])

    def test_forbidden_regional_never_queries_database(self):
        conn, _ = connection()
        with self.assertRaises(PermissionError):
            query_postgres_licenses(conn, allowed_regionals=["REG_TLSV_POA"],
                                    regional="REG_NUTRICAR")
        conn.cursor.assert_not_called()

    def test_malformed_scope_and_filters_fail_closed(self):
        cases = [{"allowed_regionals": None}, {"allowed_regionals": "REG_TLSV_POA"},
                 {"allowed_regionals": [None]}, {"allowed_regionals": [""]},
                 {"expires_within_days": True}, {"expires_within_days": -1},
                 {"expires_within_days": 3661}, {"limit": True}, {"offset": -1},
                 {"status": "arbitrary"}, {"regional": 12}]
        for case in cases:
            with self.subTest(case=case):
                conn, _ = connection()
                args = {"allowed_regionals": ["REG_TLSV_POA"], **case}
                with self.assertRaises(ValueError):
                    query_postgres_licenses(conn, **args)
                conn.cursor.assert_not_called()

    def test_driver_failure_sanitized_and_not_zero(self):
        conn, cursor = connection()
        cursor.execute.side_effect = RuntimeError("PRIVATE_PASSWORD_AND_SQL")
        with self.assertRaises(LicenseQueryError) as error:
            query_postgres_licenses(conn, allowed_regionals=["REG_TLSV_POA"])
        self.assertNotIn("PRIVATE", str(error.exception))

    def test_missing_marker_is_failure(self):
        conn, _ = connection(marker=None)
        with self.assertRaises(LicenseQueryError):
            query_postgres_licenses(conn, allowed_regionals=["REG_TLSV_POA"])

    def test_wrong_instance_is_failure(self):
        conn, cursor = connection()
        cursor.fetchone.side_effect = [("aegis", 5432)]
        with self.assertRaises(LicenseQueryError):
            query_postgres_licenses(conn, allowed_regionals=["REG_TLSV_POA"])
        cursor.fetchall.assert_not_called()

    def test_outside_scope_source_is_rejected(self):
        conn, _ = connection([license_row(code="REG_NUTRICAR")])
        with self.assertRaises(LicenseQueryError):
            query_postgres_licenses(conn, allowed_regionals=["REG_TLSV_POA"])

    def test_status_filter_preserves_collector_classification(self):
        conn, _ = connection([license_row(expired=True)])
        result = query_postgres_licenses(conn, allowed_regionals=["REG_TLSV_POA"],
                                         status="expired", now=NOW)
        self.assertEqual(result["summary"]["by_status"], {"expired": 1})


if __name__ == "__main__":
    unittest.main()
