from contextlib import redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest

from services.switch_update_v01.main import (
    MAX_FIRMWARE_BYTES,
    LoginPageParser,
    UpdateError,
    build_parser,
    classify_update,
    concise_exception_message,
    detect_supported_model,
    extract_version,
    infer_model_from_filename,
    infer_version_from_filename,
    normalize_version,
    resolve_firmware_metadata,
    validate_firmware,
    validate_url,
    version_matches,
    version_key,
)


class ValidationTests(unittest.TestCase):
    def test_preflight_and_execute_are_mutually_exclusive(self):
        parser = build_parser()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args([
                "--url", "http://192.0.2.10",
                "--username", "admin",
                "--firmware", "firmware.swi",
                "--preflight", "--execute",
            ])

    def test_parser_accepts_hidden_browser_progress_and_same_version_flags(self):
        parser = build_parser()
        args = parser.parse_args([
            "--url", "http://192.0.2.10",
            "--username", "admin",
            "--firmware", "firmware.swi",
            "--json-progress",
            "--allow-same-version",
            "--allow-downgrade",
            "--sentinel-approved",
            "--execute",
        ])
        self.assertTrue(args.json_progress)
        self.assertTrue(args.allow_same_version)
        self.assertTrue(args.allow_downgrade)
        self.assertTrue(args.sentinel_approved)

    def test_concise_exception_message_removes_multiline_stack(self):
        message = concise_exception_message(RuntimeError("stale element\nStacktrace:\ninternal"))
        self.assertEqual(message, "Falha do navegador (RuntimeError): stale element")

    def test_webui_check_and_execute_are_mutually_exclusive(self):
        parser = build_parser()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args([
                "--url", "http://192.0.2.10",
                "--username", "admin",
                "--firmware", "firmware.swi",
                "--webui-check", "--execute",
            ])

    def test_wizard_check_and_execute_are_mutually_exclusive(self):
        parser = build_parser()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args([
                "--url", "http://192.0.2.10",
                "--username", "admin",
                "--firmware", "firmware.swi",
                "--wizard-check", "--execute",
            ])

    def test_save_check_and_execute_are_mutually_exclusive(self):
        parser = build_parser()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args([
                "--url", "http://192.0.2.10",
                "--username", "admin",
                "--firmware", "firmware.swi",
                "--save-check", "--execute",
            ])

    def test_validate_url_accepts_http_ip(self):
        self.assertEqual(validate_url("http://192.0.2.10/"), ("http://192.0.2.10", "192.0.2.10"))

    def test_validate_url_rejects_hostname_in_alpha(self):
        with self.assertRaises(UpdateError):
            validate_url("https://switch.local")

    def test_validate_url_rejects_embedded_credentials(self):
        with self.assertRaises(UpdateError):
            validate_url("https://admin:secret@192.0.2.10")

    def test_validate_url_rejects_path_query_and_loopback(self):
        for url in (
            "https://192.0.2.10/admin",
            "https://192.0.2.10?next=admin",
            "http://127.0.0.1",
            "http://169.254.1.10",
        ):
            with self.subTest(url=url), self.assertRaises(UpdateError):
                validate_url(url)

    def test_validate_firmware_accepts_non_empty_swi(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "InstantOn_1830_3.4.0.6.swi"
            path.write_bytes(b"test")
            self.assertEqual(validate_firmware(path), path.resolve())

    def test_validate_firmware_rejects_other_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "firmware.bin"
            path.write_bytes(b"test")
            with self.assertRaises(UpdateError):
                validate_firmware(path)

    def test_validate_firmware_rejects_oversized_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "InstantOn_1930_3.4.0.6.swi"
            with path.open("wb") as stream:
                stream.seek(MAX_FIRMWARE_BYTES)
                stream.write(b"x")
            with self.assertRaises(UpdateError):
                validate_firmware(path)


class IdentificationTests(unittest.TestCase):
    def test_infers_four_part_version(self):
        path = Path("InstantOn_1830_3.4.0.6.swi")
        self.assertEqual(infer_version_from_filename(path), "3.4.0.6")

    def test_infers_model_from_firmware_filename(self):
        path = Path("InstantOn_1830_3.4.0.6.swi")
        self.assertEqual(infer_model_from_filename(path), "1830")

    def test_detects_supported_model(self):
        self.assertEqual(detect_supported_model(["Aruba Instant On 1930 48G"]), "1930")

    def test_rejects_ambiguous_model(self):
        with self.assertRaises(UpdateError):
            detect_supported_model(["Aruba 1830", "Aruba 1930"])

    def test_unsupported_model_returns_none(self):
        self.assertIsNone(detect_supported_model(["Aruba 2530 Switch"]))

    def test_login_page_parser_extracts_public_identity(self):
        parser = LoginPageParser()
        parser.feed("""
            <html><head><title>Instant On 1930 Switch</title></head><body>
            <input id="inputUsername" name="inputUsername">
            <input id="inputPassword" name="inputPassword" type="password">
            <input name="sysName" value="LAB-SW">
            <input name="sysDescr" value="InstantOn_1930_3.4.0.0 (6)">
            <button id="submitButton">LOGIN</button>
            </body></html>
        """)
        self.assertEqual(parser.title, "Instant On 1930 Switch")
        self.assertEqual(parser.fields["sysName"], "LAB-SW")
        self.assertIn("submitButton", parser.element_ids)


class VersionTests(unittest.TestCase):
    def test_classifies_update_same_version_and_downgrade(self):
        self.assertEqual(classify_update("3.4.0.6", "InstantOn_1930_3.3.0.0 (9)"), ("update", "3.3.0.9"))
        self.assertEqual(classify_update("3.4.0.6", "InstantOn_1930_3.4.0.0 (6)"), ("same_version", "3.4.0.6"))
        self.assertEqual(classify_update("3.3.0.9", "InstantOn_1930_3.4.0.0 (6)"), ("downgrade", "3.4.0.6"))

    def test_classification_blocks_unknown_current_version(self):
        with self.assertRaises(UpdateError):
            classify_update("3.4.0.6", "versao indisponivel")

    def test_resolves_firmware_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "InstantOn_1930_3.4.0.6.swi"
            path.write_bytes(b"firmware")
            resolved, model, version = resolve_firmware_metadata(path)
            self.assertEqual(resolved, path.resolve())
            self.assertEqual(model, "1930")
            self.assertEqual(version, "3.4.0.6")

    def test_extracts_aruba_build_version(self):
        observed = "InstantOn_1930_3.4.0.0 (6)"
        self.assertEqual(extract_version(observed), "3.4.0.6")

    def test_compares_four_part_versions(self):
        self.assertLess(version_key("3.3.0.9"), version_key("3.4.0.6"))

    def test_normalizes_version_prefix(self):
        self.assertEqual(normalize_version("Firmware: v3.4.0.6"), "v3.4.0.6")

    def test_version_matches_device_description(self):
        self.assertTrue(version_matches("3.4.0.6", "Aruba Instant On 1830, software version 3.4.0.6"))

    def test_version_matches_web_value_with_v_prefix(self):
        self.assertTrue(version_matches("3.4.0.6", "v3.4.0.6"))

    def test_version_matches_aruba_build_notation(self):
        observed = "InstantOn_1930_3.4.0.0 (6)"
        self.assertTrue(version_matches("3.4.0.6", observed))

    def test_version_rejects_different_release(self):
        self.assertFalse(version_matches("3.4.0.6", "software version 3.3.4"))


if __name__ == "__main__":
    unittest.main()
