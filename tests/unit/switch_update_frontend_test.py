from __future__ import annotations

import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

import web_config
from regional_access import ADMINISTRATIVE_OU_DN
from user_model import User, remove_user, save_user
from web_config import app


class SwitchUpdateFrontendTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()
        self.user = User({
            "username": "switch.operator",
            "dn": f"CN=Switch Operator,{ADMINISTRATIVE_OU_DN}",
            "groups": [],
        })
        save_user(self.user)
        with self.client.session_transaction() as session:
            session["_user_id"] = self.user.get_id()
            session["_fresh"] = True

    def tearDown(self):
        remove_user(self.user.get_id())

    def test_update_page_renders_required_fields_and_immediate_warning(self):
        switch = {
            "host": "SJC - SWITCH - SWTSJC-05",
            "ip": "192.0.2.21",
            "regional": "REGIONAL SAO JOSE DOS CAMPOS",
            "modelo": "HPE Networking Instant On 1930 48p",
            "status": "online",
        }
        with patch("web_config._resolver_switch_update", return_value=switch), patch.object(
            web_config.switch_update_scheduler,
            "list_firmware_inventory",
            return_value=[],
        ), patch.object(
            web_config.switch_update_scheduler,
            "get_latest_failed_schedule_for_host",
            return_value=None,
        ):
            response = self.client.get(
                "/switches/atualizar/SJC%20-%20SWITCH%20-%20SWTSJC-05"
            )

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Atualizar Switch", html)
        self.assertIn("REGIONAL SAO JOSE DOS CAMPOS", html)
        self.assertIn("HPE Networking Instant On 1930 48p", html)
        self.assertIn('id="switchCurrentVersion"', html)
        self.assertIn('id="switchCurrentVersionValue"', html)
        self.assertIn("/firmware/identity", html)
        self.assertIn('id="switchUsername"', html)
        self.assertIn('id="switchPassword"', html)
        self.assertIn('id="switchFirmware"', html)
        self.assertIn('accept=".swi"', html)
        self.assertIn("switch-update-file-row", html)
        self.assertIn('class="col-lg-9"', html)
        self.assertIn('class="col-lg-3"', html)
        self.assertIn('id="switchScheduledAt"', html)
        self.assertIn("Selecione data e hora", html)
        self.assertIn('id="switchScheduleDate"', html)
        self.assertIn('placeholder="DD/MM/AAAA"', html)
        self.assertIn('id="switchCalendarPopover"', html)
        self.assertIn('id="previousCalendarMonth"', html)
        self.assertIn('id="nextCalendarMonth"', html)
        self.assertIn('id="switchScheduleTime"', html)
        self.assertIn('id="subtractThirtyMinutes"', html)
        self.assertIn('id="addThirtyMinutes"', html)
        self.assertIn("function scheduleDateToIso", html)
        self.assertIn("function normalizeScheduleDate", html)
        self.assertIn("day = Math.max(1, Math.min(lastDay, day))", html)
        self.assertIn("if (normalized < today) normalized = today", html)
        self.assertIn("parsed.getMonth() !== month - 1", html)
        self.assertIn("digits.length === 4", html)
        self.assertIn("if (hours > 23)", html)
        self.assertIn("hours = 23", html)
        self.assertIn("minutes = 59", html)
        self.assertIn("function normalizeScheduleToFuture", html)
        self.assertIn("nearestFuture.setMinutes(nearestFuture.getMinutes() + 1)", html)
        self.assertIn("Selecione um horário futuro", html)
        self.assertIn("form.reportValidity();", html)
        self.assertIn("adjustScheduleTime(-30)", html)
        self.assertIn("adjustScheduleTime(30)", html)
        self.assertIn("será executada imediatamente", html)
        self.assertIn("Continuar", html)
        self.assertIn("Voltar", html)
        self.assertIn('id="failedActions"', html)
        self.assertIn("Reagendar", html)

    def test_global_csrf_token_is_accepted_by_firmware_api(self):
        token_response = self.client.get("/api/switches/firmware/csrf")
        self.assertEqual(token_response.status_code, 200)
        token = token_response.get_json()["csrf_token"]

        response = self.client.post(
            "/api/switches/SW-INEXISTENTE/firmware/preflight",
            headers={"X-CSRF-Token": token},
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("Switch nao encontrado", response.get_json()["message"])

    def test_update_page_denies_regional_support_without_operator_permission(self):
        remove_user(self.user.get_id())
        regional_user = User({
            "username": self.user.get_id(),
            "dn": (
                "CN=Regional Support,OU=Departamentos,OU=Bahia,"
                "OU=Regionais,DC=example,DC=local"
            ),
            "groups": [
                "CN=GGS_SUPORTE_BAHIA,OU=Grupos de Seguranca,"
                "OU=Grupos,DC=example,DC=local"
            ],
        })
        save_user(regional_user)

        response = self.client.get(
            "/switches/atualizar/SJC-SWITCH",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/switches"))

    def test_edit_page_uses_detected_model_when_cadastro_is_empty(self):
        switch = {
            "host": "SW-LAB",
            "ip": "192.0.2.21",
            "regional": "LAB",
            "modelo": "Não informado",
            "local": "Rack",
        }
        inventory = [{
            "host": "192.0.2.21",
            "switch_name": "SW-LAB",
            "model": "HPE Networking Instant On 1830 48p",
        }]
        with patch.object(
            web_config.gerenciador_switches,
            "obter_switch",
            return_value=switch,
        ), patch.object(
            web_config.gerenciador_switches,
            "listar_regionais",
            return_value=["LAB"],
        ), patch.object(
            web_config.switch_update_scheduler,
            "list_firmware_inventory",
            return_value=inventory,
        ), patch.object(
            web_config.switch_update_scheduler,
            "list_active_schedules_for_regional",
            return_value=[],
        ):
            response = self.client.get("/switches/editar/SW-LAB")

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'value="HPE Networking Instant On 1830 48p"',
            response.get_data(as_text=True),
        )
        self.assertIn("após salvar uma edição manual", response.get_data(as_text=True))

    def test_edit_page_locks_core_change_when_regional_has_active_update(self):
        switch = {
            "host": "SW-LAB",
            "ip": "192.0.2.21",
            "regional": "LAB",
            "modelo": "1930",
            "local": "Rack",
            "is_core": False,
        }
        active = [{"id": "job-1", "switch_name": "SW-02", "status": "scheduled"}]
        with patch.object(
            web_config.gerenciador_switches, "obter_switch", return_value=switch
        ), patch.object(
            web_config.gerenciador_switches, "listar_regionais", return_value=["LAB"]
        ), patch.object(
            web_config.switch_update_scheduler, "list_firmware_inventory", return_value=[]
        ), patch.object(
            web_config.switch_update_scheduler,
            "list_active_schedules_for_regional",
            return_value=active,
        ):
            response = self.client.get("/switches/editar/SW-LAB")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="is_core" name="is_core" value="1"\n                   disabled', html)
        self.assertIn("Identificação bloqueada", html)
        self.assertIn("1 atualização(ões) ativa(s)", html)

    def test_edit_post_rejects_core_change_when_regional_has_active_update(self):
        switch = {
            "host": "SW-LAB",
            "ip": "192.0.2.21",
            "regional": "LAB",
            "modelo": "1930",
            "local": "Rack",
            "is_core": False,
        }
        with patch.object(
            web_config.gerenciador_switches, "obter_switch", return_value=switch
        ), patch.object(
            web_config.switch_update_scheduler,
            "list_active_schedules_for_regional",
            return_value=[{"id": "job-1", "status": "scheduled"}],
        ), patch.object(
            web_config.gerenciador_switches, "atualizar_metadados"
        ) as update_metadata:
            with self.client.session_transaction() as session:
                session["_csrf_token"] = "core-lock-test-token"
            response = self.client.post(
                "/switches/editar/SW-LAB",
                data={
                    "modelo": "1930",
                    "local": "Rack",
                    "is_core": "1",
                    "csrf_token": "core-lock-test-token",
                },
            )

        self.assertEqual(response.status_code, 302)
        update_metadata.assert_not_called()

    def test_card_places_green_update_action_between_verify_and_edit(self):
        template = (Path(app.template_folder) / "switches.html").read_text(encoding="utf-8")
        verify_position = template.index("Verificar\n")
        update_position = template.index("url_for('atualizar_switch'")
        edit_position = template.index("onclick=\"editarSwitch")

        self.assertLess(verify_position, update_position)
        self.assertLess(update_position, edit_position)
        self.assertIn("btn-outline-success switch-icon-button", template)
        self.assertIn("bi-arrow-up-circle", template)
        self.assertIn("{% if sentinel_access.operator %}", template)

    def test_switch_card_uses_standard_field_order_and_inline_check_time(self):
        template = (Path(app.template_folder) / "switches.html").read_text(encoding="utf-8")
        ip_position = template.index("<strong>IP:</strong>")
        local_position = template.index("<strong>Local:</strong>")
        status_position = template.index("<strong>Status:</strong>")
        model_position = template.index("<strong>Modelo:</strong>")
        firmware_position = template.index("<strong>Firmware:</strong>")

        self.assertLess(ip_position, local_position)
        self.assertLess(local_position, status_position)
        self.assertLess(status_position, model_position)
        self.assertLess(model_position, firmware_position)
        self.assertIn("Verificado em <span class=\"verification-value\">", template)

    def test_quick_actions_include_bulk_firmware_check_and_descriptions(self):
        template = (Path(app.template_folder) / "switches.html").read_text(encoding="utf-8")

        self.assertIn('id="btn-verificar-firmwares"', template)
        self.assertIn("btn-outline-success btn-lg quick-action-control", template)
        self.assertIn("height: 82px", template)
        self.assertIn("grid-template-columns: 24px minmax(0, 1fr) 24px", template)
        self.assertIn("top: calc(50% - 0.5rem)", template)
        self.assertIn("left: calc(50% - 0.5rem)", template)
        self.assertEqual(template.count('class="quick-action-label"'), 4)
        self.assertIn("verificarFirmwaresSwitches(this)", template)
        self.assertIn("/api/switches/firmwares/verificar", template)
        self.assertIn("WebUI pública de cada switch", template)
        self.assertIn("sem utilizar credenciais", template)
        self.assertIn("Histórico de atualizações:", template)
        self.assertIn("job.kind === 'switches-firmware'", template)
        self.assertIn("switch-firmware-version", template)
        self.assertIn("switch-firmware-checked", template)
        self.assertIn(".addClass('d-block')", template)
        self.assertIn("média de ${average}s por switch", template)
        self.assertIn("return `${datePart} às ${timePart}`", template)

    def test_compact_model_reuses_http_metadata_without_another_request(self):
        identity_with_ports_before_family = SimpleNamespace(
            title="Instant On - Login Form",
            sys_descr=(
                "HPE Networking Instant On Switch 48p Gigabit 4p SFP "
                "1830 JL814A, InstantOn_1830_3.4.0.0 (6)"
            ),
            model="1830",
            page_text="",
        )
        self.assertEqual(
            web_config._compact_switch_model(identity_with_ports_before_family),
            "HPE Networking Instant On 1830 48p",
        )

        identity_from_login = SimpleNamespace(
            title="Instant On",
            sys_descr="InstantOn_1830_3.4.0.6",
            model="1830",
            page_text=(
                "HPE Networking Instant On 1830 48p Gigabit "
                "4p SFP Switch JL814A"
            ),
        )
        self.assertEqual(
            web_config._compact_switch_model(identity_from_login),
            "HPE Networking Instant On 1830 48p",
        )

        identity = SimpleNamespace(
            title="Instant On",
            sys_descr="InstantOn_1960_3.1.0.0 (12)",
            model=None,
            page_text=(
                "HPE Networking Instant On 1960 24p Gigabit "
                "2p SFP+ Switch JL806A"
            ),
        )
        self.assertEqual(
            web_config._compact_switch_model(identity),
            "HPE Networking Instant On 1960 24p",
        )

        identity_without_ports = SimpleNamespace(
            title="Instant On 1930 Switch",
            sys_descr="InstantOn_1930_3.3.0.0 (9)",
            model="1930",
        )
        self.assertEqual(
            web_config._compact_switch_model(
                identity_without_ports,
                "HPE Networking Instant On 1930 48p",
            ),
            "HPE Networking Instant On 1930 48p",
        )

    def test_manual_model_has_priority_over_detected_model(self):
        manual = "HPE Networking Instant On 1830 48p Gigabit 4p SFP Switch JL814A"
        self.assertEqual(
            web_config._preferred_switch_model(
                manual,
                "HPE Networking Instant On 1830 48p",
                "manual",
            ),
            manual,
        )
        self.assertEqual(
            web_config._preferred_switch_model(
                "Não informado",
                "HPE Networking Instant On 1830 48p",
            ),
            "HPE Networking Instant On 1830 48p",
        )

    def test_bulk_firmware_job_records_success_and_continues_after_failure(self):
        job_id = web_config._create_background_job("switches-firmware", total=2)
        switches = [
            {
                "host": "SW-OK",
                "ip": "192.0.2.10",
                "modelo": "HPE Networking Instant On 1930 48p",
            },
            {"host": "SW-SEM-IP", "ip": "", "modelo": "1930"},
        ]
        identity = SimpleNamespace(
            sys_descr="InstantOn_1930_3.3.0.9",
            model="1930",
        )
        inventory = {
            "current_version": "3.3.0.9",
            "model": "HPE Networking Instant On 1930 48p",
            "checked_at_brasilia": "2026-10-05T10:00:00-03:00",
        }

        with patch("web_config.fetch_web_identity", return_value=identity), patch.object(
            web_config.switch_update_scheduler,
            "record_firmware_identity",
            return_value=inventory,
        ), patch.object(
            web_config.gerenciador_switches,
            "atualizar_modelos_detectados",
            return_value={"SW-OK": "HPE Networking Instant On 1930 48p"},
        ):
            web_config._run_switch_firmware_inventory_job(job_id, switches)

        job = web_config._get_background_job(job_id)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["result"]["successful"], 1)
        self.assertEqual(job["result"]["failed"], 1)
        self.assertTrue(job["result"]["resultados"]["SW-OK"]["success"])
        self.assertEqual(
            job["result"]["resultados"]["SW-OK"]["model"],
            "HPE Networking Instant On 1930 48p",
        )
        self.assertFalse(job["result"]["resultados"]["SW-SEM-IP"]["success"])

    def test_password_is_not_persisted_in_browser_storage(self):
        template = (Path(app.template_folder) / "atualizar_switch.html").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("localStorage", template)
        self.assertNotIn("sessionStorage", template)
        self.assertIn('autocomplete="current-password"', template)
        self.assertIn("passwordInput.value = '';", template)

    def test_core_conflict_modal_lists_regional_and_applies_suggested_time(self):
        template = (Path(app.template_folder) / "atualizar_switch.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('id="coreScheduleConflictModal"', template)
        self.assertIn('id="coreRegionalSchedules"', template)
        self.assertIn('id="coreScheduleDate"', template)
        self.assertIn('id="coreScheduleTime"', template)
        self.assertIn('id="toggleCoreScheduleCalendar"', template)
        self.assertIn("CORE_SCHEDULE_CONFLICT", template)
        self.assertIn("REGIONAL_CORE_ORDER_CONFLICT", template)
        self.assertIn("showCoreScheduleConflict", template)
        self.assertIn("applySuggestedCoreSchedule", template)

    def test_history_page_opens_job_received_from_notification_link(self):
        template = (Path(app.template_folder) / "historico_atualizacoes_switches.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("pageParams.get('job')", template)
        self.assertIn("pageParams.get('q')", template)
        self.assertIn("item.dataset.jobId === targetJobId", template)
        self.assertIn("await toggleDetail(targetButton)", template)
        self.assertIn("job.status === 'failed'", template)
        self.assertIn("Reagendar", template)
        self.assertIn('class="btn btn-success ms-auto"', template)
        self.assertIn("justify-content-between", template)


if __name__ == "__main__":
    unittest.main()
