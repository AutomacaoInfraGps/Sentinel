from __future__ import annotations

import json
import subprocess
import unittest

from alertad.contracts import DirectoryResolutionStatus
from alertad.directory import (
    CachingDirectoryResolver,
    DirectoryPermanentError,
    DirectoryRecord,
    DirectoryTemporaryError,
    PowerShellADWSLookupClient,
    sid_to_bytes,
)


SID = "S-1-5-21-1000000000-2000000000-3000000000-1101"


class FakeDirectoryClient:
    def __init__(self, result=()) -> None:
        self.result = result
        self.calls: list[tuple[str, bytes]] = []

    def lookup_sid(self, sid: str, sid_bytes: bytes):
        self.calls.append((sid, sid_bytes))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class DirectoryTests(unittest.TestCase):
    def test_adws_rejects_non_finite_timeout(self) -> None:
        with self.assertRaisesRegex(ValueError, "finito"):
            PowerShellADWSLookupClient(timeout_seconds=float("inf"))

    def test_sid_is_converted_to_active_directory_binary_form(self) -> None:
        value = sid_to_bytes("S-1-5-32-544")

        self.assertEqual(value.hex(), "01020000000000052000000020020000")

    def test_success_returns_user_details(self) -> None:
        client = FakeDirectoryClient(
            (
                DirectoryRecord(
                    SID,
                    "usuario.teste",
                    "EXAMPLE",
                    "Usuário Teste",
                    ("top", "person", "organizationalPerson", "user"),
                ),
            )
        )

        result = CachingDirectoryResolver(client).resolve_sid(SID)

        self.assertEqual(result.status, DirectoryResolutionStatus.RESOLVED)
        self.assertEqual(result.directory_object.account_name, "usuario.teste")
        self.assertEqual(result.directory_object.domain_name, "EXAMPLE")
        self.assertEqual(result.directory_object.object_type, "user")

    def test_not_found_and_non_user_are_distinct(self) -> None:
        not_found = CachingDirectoryResolver(FakeDirectoryClient()).resolve_sid(SID)
        computer = CachingDirectoryResolver(
            FakeDirectoryClient(
                (DirectoryRecord(SID, "PC01$", "EXAMPLE", None, ("user", "computer")),)
            )
        ).resolve_sid(SID)

        self.assertEqual(not_found.status, DirectoryResolutionStatus.NOT_FOUND)
        self.assertEqual(not_found.error_code, "sid_not_found")
        self.assertEqual(computer.status, DirectoryResolutionStatus.PERMANENT_FAILURE)
        self.assertEqual(computer.error_code, "object_not_user")

    def test_temporary_and_permanent_failures_are_classified(self) -> None:
        temporary = CachingDirectoryResolver(
            FakeDirectoryClient(DirectoryTemporaryError())
        ).resolve_sid(SID)
        permanent = CachingDirectoryResolver(
            FakeDirectoryClient(DirectoryPermanentError())
        ).resolve_sid(SID)

        self.assertEqual(temporary.status, DirectoryResolutionStatus.TEMPORARY_FAILURE)
        self.assertEqual(permanent.status, DirectoryResolutionStatus.PERMANENT_FAILURE)

    def test_invalid_sid_never_calls_directory(self) -> None:
        client = FakeDirectoryClient()

        result = CachingDirectoryResolver(client).resolve_sid("not-a-sid")

        self.assertEqual(result.status, DirectoryResolutionStatus.PERMANENT_FAILURE)
        self.assertEqual(result.error_code, "invalid_sid")
        self.assertEqual(client.calls, [])

    def test_cache_expires_and_temporary_failure_is_not_cached(self) -> None:
        now = [10.0]
        record = DirectoryRecord(SID, "usuario", "EXAMPLE", None, ("user",))
        client = FakeDirectoryClient((record,))
        resolver = CachingDirectoryResolver(
            client,
            cache_ttl_seconds=5,
            clock=lambda: now[0],
        )

        resolver.resolve_sid(SID)
        resolver.resolve_sid(SID)
        self.assertEqual(len(client.calls), 1)

        now[0] = 16.0
        resolver.resolve_sid(SID)
        self.assertEqual(len(client.calls), 2)

        unavailable = FakeDirectoryClient(DirectoryTemporaryError())
        temporary_resolver = CachingDirectoryResolver(unavailable)
        temporary_resolver.resolve_sid(SID)
        temporary_resolver.resolve_sid(SID)
        self.assertEqual(len(unavailable.calls), 2)

    def test_adws_lookup_uses_integrated_identity_without_sid_in_command(self) -> None:
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "status": "resolved",
                        "account_name": "usuario.teste",
                        "domain_name": "EXAMPLE",
                        "display_name": "Usuário Teste",
                    }
                ),
                stderr="",
            )

        client = PowerShellADWSLookupClient(
            server=None,
            process_runner=run,
            powershell_executable="powershell.exe",
        )

        records = client.lookup_sid(SID, sid_to_bytes(SID))

        self.assertEqual(records[0].account_name, "usuario.teste")
        command, options = calls[0]
        self.assertIn("-NonInteractive", command)
        self.assertNotIn(SID, " ".join(command))
        self.assertEqual(options["env"]["ALERTAD_ADWS_LOOKUP_SID"], SID)
        self.assertEqual(options["env"]["ALERTAD_ADWS_INTERACTIVE"], "0")
        self.assertNotIn("password", " ".join(command).casefold())

    def test_adws_interactive_mode_uses_native_credential_prompt(self) -> None:
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(
                command,
                0,
                stdout='{"status":"not_found","error_code":"sid_not_found"}',
                stderr="",
            )

        client = PowerShellADWSLookupClient(
            interactive_credentials=True,
            process_runner=run,
            powershell_executable="powershell.exe",
        )

        self.assertEqual(client.lookup_sid(SID, sid_to_bytes(SID)), ())
        command, options = calls[0]
        self.assertNotIn("-NonInteractive", command)
        self.assertEqual(options["env"]["ALERTAD_ADWS_INTERACTIVE"], "1")
        self.assertNotIn("ALERTAD_ADWS_PASSWORD", options["env"])
        self.assertNotIn("ALERTAD_ADWS_CREDENTIAL", options["env"])

    def test_adws_failures_are_sanitized_and_classified(self) -> None:
        def temporary(command, **kwargs):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    '{"status":"temporary_failure",'
                    '"error_code":"directory_unavailable"}'
                ),
                stderr="synthetic detail that must not be propagated",
            )

        resolver = CachingDirectoryResolver(
            PowerShellADWSLookupClient(
                process_runner=temporary,
                powershell_executable="powershell.exe",
            )
        )

        result = resolver.resolve_sid(SID)

        self.assertEqual(result.status, DirectoryResolutionStatus.TEMPORARY_FAILURE)
        self.assertEqual(result.error_code, "directory_unavailable")

    def test_adws_timeout_is_temporary(self) -> None:
        def timeout(command, **kwargs):
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        resolver = CachingDirectoryResolver(
            PowerShellADWSLookupClient(
                process_runner=timeout,
                powershell_executable="powershell.exe",
            )
        )

        result = resolver.resolve_sid(SID)

        self.assertEqual(result.status, DirectoryResolutionStatus.TEMPORARY_FAILURE)
        self.assertEqual(result.error_code, "directory_unavailable")


if __name__ == "__main__":
    unittest.main()
