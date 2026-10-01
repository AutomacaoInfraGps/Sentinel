import unittest
from unittest.mock import patch

from run_web_service import _waitress_proxy_options


class RunWebServiceTest(unittest.TestCase):
    def test_proxy_trust_is_disabled_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(_waitress_proxy_options("0.0.0.0"), {})

    def test_only_local_iis_proxy_headers_are_trusted(self):
        with patch.dict(
            "os.environ",
            {"SENTINEL_TRUST_PROXY": "true"},
            clear=True,
        ):
            options = _waitress_proxy_options("127.0.0.1")

        self.assertEqual(options["trusted_proxy"], "127.0.0.1")
        self.assertEqual(options["trusted_proxy_count"], 1)
        self.assertEqual(
            options["trusted_proxy_headers"],
            {"x-forwarded-for", "x-forwarded-proto"},
        )
        self.assertTrue(options["clear_untrusted_proxy_headers"])

    def test_proxy_mode_refuses_network_listener(self):
        with patch.dict(
            "os.environ",
            {"SENTINEL_TRUST_PROXY": "true"},
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                _waitress_proxy_options("0.0.0.0")


if __name__ == "__main__":
    unittest.main()
