from __future__ import annotations

import tempfile
import unittest
import sys
import types
from pathlib import Path
from unittest.mock import patch

from alertad.graph import (
    ClientCredentialTokenProvider,
    DelegatedTokenProvider,
    GraphAuthenticationError,
)


class FakeCache:
    has_state_changed = True

    @staticmethod
    def serialize() -> str:
        return "synthetic-cache-content"


class GraphCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.cache_file = Path(self.temporary_directory.name) / "cache.bin"
        self.provider = DelegatedTokenProvider(
            "synthetic-tenant",
            "synthetic-client",
            "account@example.invalid",
            self.cache_file,
        )
        self.provider._cache = FakeCache()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_cache_is_replaced_atomically(self) -> None:
        self.provider._save_cache()

        self.assertEqual(
            self.cache_file.read_text(encoding="utf-8"),
            "synthetic-cache-content",
        )
        self.assertEqual(list(self.cache_file.parent.glob("*.tmp")), [])

    def test_failed_replace_preserves_previous_cache(self) -> None:
        self.cache_file.write_text("previous-cache", encoding="utf-8")

        with patch("alertad.graph.os.replace", side_effect=OSError("simulated")):
            with self.assertRaisesRegex(GraphAuthenticationError, "atualizar"):
                self.provider._save_cache()

        self.assertEqual(self.cache_file.read_text(encoding="utf-8"), "previous-cache")
        self.assertEqual(list(self.cache_file.parent.glob("*.tmp")), [])

    def test_msal_transport_receives_finite_timeout_and_timeout_is_retryable(self) -> None:
        captured = {}

        def blocked_application(**kwargs):
            captured.update(kwargs)
            raise TimeoutError("synthetic blocked authentication")

        msal_module = types.ModuleType("msal")
        msal_module.ConfidentialClientApplication = blocked_application
        provider = ClientCredentialTokenProvider(
            "synthetic-tenant",
            "synthetic-client",
            "synthetic-secret",
            authentication_timeout_seconds=17,
        )

        with patch.dict(sys.modules, {"msal": msal_module}):
            with self.assertRaises(GraphAuthenticationError) as captured_error:
                provider.get_token()

        self.assertEqual(captured["timeout"], 17.0)
        self.assertTrue(captured_error.exception.retryable)
        self.assertEqual(captured_error.exception.failure_kind, "temporary")

    def test_delegated_renewal_uses_finite_timeout_and_classifies_transport(self) -> None:
        captured = {}

        class Cache:
            has_state_changed = False

        class Application:
            @staticmethod
            def get_accounts(**kwargs):
                del kwargs
                return [{"username": "account@example.invalid"}]

            @staticmethod
            def acquire_token_silent(*args, **kwargs):
                del args, kwargs
                raise TimeoutError("synthetic renewal timeout")

        def public_application(**kwargs):
            captured.update(kwargs)
            return Application()

        msal_module = types.ModuleType("msal")
        msal_module.SerializableTokenCache = Cache
        msal_module.PublicClientApplication = public_application
        provider = DelegatedTokenProvider(
            "synthetic-tenant",
            "synthetic-client",
            "account@example.invalid",
            self.cache_file,
            authentication_timeout_seconds=19,
        )

        with patch.dict(sys.modules, {"msal": msal_module}):
            with self.assertRaises(GraphAuthenticationError) as captured_error:
                provider.get_token()

        self.assertEqual(captured["timeout"], 19.0)
        self.assertTrue(captured_error.exception.retryable)
        self.assertEqual(captured_error.exception.failure_kind, "temporary")

    def test_temporarily_unavailable_is_classified_as_retryable(self) -> None:
        class FakeApplication:
            @staticmethod
            def acquire_token_for_client(**kwargs):
                del kwargs
                return {"error": "temporarily_unavailable"}

        provider = ClientCredentialTokenProvider(
            "synthetic-tenant",
            "synthetic-client",
            "synthetic-secret",
        )
        provider._application = FakeApplication()

        with self.assertRaises(GraphAuthenticationError) as captured_error:
            provider.get_token()

        self.assertTrue(captured_error.exception.retryable)
        self.assertEqual(captured_error.exception.failure_kind, "temporary")


if __name__ == "__main__":
    unittest.main()
