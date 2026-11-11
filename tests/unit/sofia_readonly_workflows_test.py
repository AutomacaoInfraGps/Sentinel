import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from sofia.n8n.build_readonly_workflows import build_workflows, expression, main as build_cli, plan_schema
from sofia.service_auth import canonical_request


def exports():
    def item(name, kind="set", parameters=None, credentials=None):
        return {"name": name, "id": name, "type": "n8n-nodes-base." + kind,
                "parameters": parameters or {}, "credentials": credentials or {}}

    fields = {"assignments": {"assignments": [{"name": "canonical", "value": "old"}]}}
    main = {"id": "test-main", "name": "Test main", "settings": {}, "nodes": [
        item("Webhook", "webhook", {"path": "existing-path", "authentication": "headerAuth"},
             {"httpHeaderAuth": {"id": "test-header"}}),
        item("Crypto"), item("Edit Fields"), item("Crypto2"),
        item("Edit Fields1", parameters=fields), item("Crypto1"),
        item("Registrar execução no Sentinel", "httpRequest", {
            "url": "https://sentinel.example.test/api/internal/sofia/v1/executions/register"}),
        item("Memória Principal V3", credentials={"postgres": {"id": "test-isolated-memory"}}),
        item("Ollama Operacional", parameters={"model": "qwen3:4b-instruct"}),
        item("Respond to Webhook", "respondToWebhook", {"options": {"responseCode": 200}})]}
    inventory = {"id": "test-inventory", "name": "Test inventory", "nodes": [
        item("When Executed by Another Workflow", "executeWorkflowTrigger", {
            "workflowInputs": {"values": [{"name": "resource", "type": "string"}]}}),
        item("Edit Fields", parameters={"assignments": {"assignments": [
            {"name": "target", "value": "/api/internal/sofia/v1/inventory/query"},
            {"name": "body_raw", "value": "={{ JSON.stringify({resource:$json.resource}) }}"}]}}),
        item("Edit Fields1", parameters=fields), item("HTTP", "httpRequest", {})]}
    return main, inventory


@unittest.skipUnless(shutil.which("node"), "Node is required to validate n8n expressions")
class SofiaReadonlyWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.main, self.inventory = build_workflows(*exports())

    def evaluate(self, value, data=None, inputs=None):
        self.assertTrue(value.startswith("={{"))
        self.assertTrue(value.endswith("}}"))
        # Tournament splits on the first closing delimiter, including inside JS objects.
        self.assertNotIn("}}", value[3:-2], "n8n would close this expression prematurely")
        runner = r"""
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const lookup = () => ({first: () => ({json:input.inputs})});
try {
  let result;
  if (process.env.SOFIA_N8N_WORKFLOW_PATH) {
    const {Expression} = require(process.env.SOFIA_N8N_WORKFLOW_PATH);
    result = new Expression('America/Sao_Paulo').resolveSimpleParameterValue(input.code, {$json:input.data,$:lookup});
  } else if (process.env.SOFIA_TOURNAMENT_PATH) {
    const {Tournament} = require(process.env.SOFIA_TOURNAMENT_PATH);
    const engine = new Tournament(error => {throw error;});
    result = engine.execute(input.code.slice(1), {$json:input.data,$:lookup,JSON,Object,Array,Number,Error});
  } else {
    result = new Function('$json', '$', 'return (' + input.code.slice(3,-2) + ');')(input.data,lookup);
  }
  if (result === undefined) throw new Error('A expressão não retornou um valor válido.');
  process.stdout.write(JSON.stringify({result}));
} catch (error) { process.stdout.write(JSON.stringify({error:error.message})); }
"""
        result = subprocess.run(["node", "-e", runner], input=json.dumps({
            "code": value, "data": data or {}, "inputs": inputs or {}}),
            capture_output=True, text=True, encoding="utf-8", check=True)
        return json.loads(result.stdout)

    def field(self, workflow, node_name, field_name):
        item = next(node for node in workflow["nodes"] if node["name"] == node_name)
        return next(field["value"] for field in item["parameters"]["assignments"]["assignments"]
                    if field["name"] == field_name)

    def plan(self, **changes):
        return {"mode": "query", "reply": "", "resource": "aps", "regional": "",
                "status": "offline", "search": "", "view": "list",
                "fields": ["name", "ip", "regional"], "limit": 20, "offset": 0, **changes}

    def test_existing_ids_authentication_and_isolated_credentials_are_preserved(self):
        self.assertEqual(self.main["id"], "test-main")
        self.assertEqual(self.inventory["id"], "test-inventory")
        webhook = self.main["nodes"][0]
        self.assertEqual(webhook["parameters"]["path"], "existing-path")
        self.assertEqual(webhook["credentials"]["httpHeaderAuth"]["id"], "test-header")
        self.assertFalse(self.main["active"])
        for node in self.main["nodes"]:
            if node["type"].endswith("postgres"):
                self.assertEqual(node["credentials"]["postgres"]["id"], "test-isolated-memory")
        self.assertFalse(any("langchain" in node["type"] for node in self.main["nodes"]))
        self.assertEqual(sum(node["name"] == "Interpretar pedido" for node in self.main["nodes"]), 1)

    def test_model_receives_only_short_context_and_identity(self):
        http = next(node for node in self.main["nodes"] if node["name"] == "Interpretar pedido")
        result = self.evaluate(http["parameters"]["body"], {"context": {"previous_query": None}},
            {"body": {"message": "Quais APs?", "user_context": {"display_name": "Teste", "relationship": "creator"},
                      "sentinel_scope_token": "PRIVATE_SCOPE", "allowed_regionals": ["PRIVATE_REGION"]}})
        body = json.loads(result["result"])
        self.assertEqual(body["format"], plan_schema())
        self.assertEqual(body["options"]["num_thread"], 8)
        self.assertNotIn("PRIVATE_SCOPE", str(body))
        self.assertNotIn("PRIVATE_REGION", str(body))
        message = json.loads(body["messages"][1]["content"])
        self.assertEqual(message["user_context"], {"display_name": "Teste", "relationship": "creator"})
        self.assertIn("não altera a identidade autenticada", body["messages"][0]["content"])

    def test_validation_rejects_truncated_invalid_or_executable_plans(self):
        code = self.field(self.main, "Validar plano", "plan")
        valid = {"done": True, "done_reason": "stop", "message": {"content": json.dumps(self.plan())}}
        self.assertEqual(self.evaluate(code, valid)["result"], self.plan())
        for invalid in [self.plan(url="https://outside.test"), self.plan(limit=1000),
                        self.plan(fields=["password"]), self.plan(resource="credentials"),
                        self.plan(reply="Invented operational answer")]:
            response = {**valid, "message": {"content": json.dumps(invalid)}}
            self.assertIn("error", self.evaluate(code, response))
        self.assertIn("error", self.evaluate(code, {**valid, "done_reason": "length"}))

    def test_social_plan_matches_the_completed_ollama_response(self):
        plan = self.plan(mode="chat", resource="", status="", fields=[], view="count",
                         reply="Bom dia! Tudo bem, obrigado por perguntar. Como posso ajudar hoje?")
        response = {"done": True, "done_reason": "stop", "message": {"role": "assistant",
                    "content": json.dumps(plan, ensure_ascii=False)}}
        self.assertEqual(self.evaluate(self.field(self.main, "Validar plano", "plan"), response)["result"], plan)

    def test_clipboard_export_returns_an_object_without_surrounding_text(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            main_file = directory / "main.json"
            inventory_file = directory / "inventory.json"
            main_export, inventory_export = exports()
            main_file.write_text(json.dumps(main_export), encoding="utf-8")
            inventory_file.write_text(json.dumps(inventory_export), encoding="utf-8")
            with patch("sys.argv", ["build_readonly_workflows", "--main", str(main_file),
                       "--inventory", str(inventory_file), "--output", str(directory)]), patch("builtins.print"):
                build_cli()
            text = (directory / "validar-plano-expression.txt").read_text(encoding="utf-8")
            self.assertEqual(text, text.strip())
            plan = self.plan(mode="chat", resource="", status="", fields=[], reply="Bom dia!")
            response = {"done": True, "done_reason": "stop", "message": {"content": json.dumps(plan)}}
            result = self.evaluate("=" + text, response)["result"]
            self.assertIsInstance(result, dict)
            self.assertEqual(result, plan)
            interpreter = (directory / "interpretar-pedido-expression.txt").read_text(encoding="utf-8")
            self.assertEqual(interpreter, interpreter.strip())
            request = self.evaluate("=" + interpreter, {"context": {}},
                                    {"body": {"message": "Sabe quem sou eu?",
                                              "user_context": {"display_name": "Teste", "relationship": "creator"}}})
            body = json.loads(request["result"])
            self.assertEqual(json.loads(body["messages"][1]["content"])["user_context"]["display_name"], "Teste")
            storage = (directory / "guardar-conversa-expression.txt").read_text(encoding="utf-8")
            self.assertEqual(storage, storage.strip())
            parameters = self.evaluate("=" + storage, {"reply": "Bom dia!", "plan": plan},
                                       {"body": {"conversation_id": "session", "message": "Oi"}})["result"]
            self.assertIsInstance(parameters, list)
            self.assertEqual(len(parameters), 3)

    def test_social_identity_in_regional_does_not_drop_reply_or_memory_parameters(self):
        plan = self.plan(mode="chat", resource="", status="", regional="Roosevelt H D Andrade Pimentel",
                         fields=["name", "status"], view="detail", reply="Você é Roosevelt, meu criador.")
        response = {"done": True, "done_reason": "stop", "message": {"content": json.dumps(plan)}}
        result = self.evaluate(self.field(self.main, "Validar plano", "plan"), response)["result"]
        self.assertEqual(result["reply"], plan["reply"])
        self.assertEqual(result["regional"], "")
        self.assertEqual(result["fields"], [])
        social_reply = self.evaluate(self.field(self.main, "Resposta de conversa", "reply"), {"plan": result})["result"]
        prepared = {"reply": social_reply, "plan": result, "page": {"next_offset": None}}
        storage = next(node for node in self.main["nodes"] if node["name"] == "Guardar conversa")
        parameters = self.evaluate(storage["parameters"]["options"]["queryReplacement"], prepared,
                                   {"body": {"conversation_id": "session", "message": "Sabe quem sou eu?"}})["result"]
        self.assertEqual(json.loads(parameters[2])["data"]["content"], plan["reply"])
        self.assertIsNone(json.loads(parameters[2])["sofia_query"])

    def test_memory_parameters_use_validated_plan_when_input_has_no_plan_or_page(self):
        storage = next(node for node in self.main["nodes"] if node["name"] == "Guardar conversa")
        result = self.evaluate(storage["parameters"]["options"]["queryReplacement"],
                               {"reply": "Consulta concluída."},
                               {"plan": self.plan(), "body": {"conversation_id": "session", "message": "Quantos APs?"}})["result"]
        self.assertEqual(len(result), 3)
        self.assertIsNone(json.loads(result[2])["sofia_query"]["next_offset"])

    def test_unmentioned_regional_is_removed_but_explicit_and_previous_are_preserved(self):
        expression_value = self.field(self.main, "Validar plano", "plan")
        cases = [
            ("Quantos APs temos offline?", "sul", None, ""),
            ("Quantos APs temos offline em Araras?", "REG_ARARAS", None, "REG_ARARAS"),
            ("E quais são?", "REG_ARARAS", {"regional": "REG_ARARAS"}, "REG_ARARAS"),
        ]
        for message, regional, previous, expected in cases:
            with self.subTest(message=message):
                response = {"done": True, "done_reason": "stop",
                            "message": {"content": json.dumps(self.plan(regional=regional))}}
                inputs = {"body": {"message": message}, "context": {"previous_query": previous}}
                result = self.evaluate(expression_value, response, inputs)["result"]
                self.assertEqual(result["regional"], expected)

    def test_memory_parameters_preserve_messages_and_query_pagination(self):
        storage = next(node for node in self.main["nodes"] if node["name"] == "Guardar conversa")
        value = storage["parameters"]["options"]["queryReplacement"]
        for mode in ("chat", "query"):
            with self.subTest(mode=mode):
                plan = self.plan(mode=mode)
                data = {"reply": "Resposta com vírgula, aspas e acento.", "plan": plan,
                        "page": {"next_offset": 20}}
                inputs = {"body": {"conversation_id": "test-session", "message": "Bom dia!"}}
                result = self.evaluate(value, data, inputs)["result"]
                self.assertIsInstance(result, list)
                self.assertEqual(result[0], "test-session:v4")
                self.assertEqual(json.loads(result[1])["data"]["content"], "Bom dia!")
                saved = json.loads(result[2])
                self.assertEqual(saved["data"]["content"], data["reply"])
                self.assertEqual(saved["sofia_kind"], mode)
                self.assertEqual(saved["sofia_query"], {**plan, "next_offset": 20} if mode == "query" else None)

    def test_subworkflow_signs_exact_body_and_fixed_target(self):
        data = {"plan": self.plan(), "sentinel_scope_token": "synthetic-scope", "resource": "aps"}
        target = self.evaluate(self.field(self.inventory, "Edit Fields", "target"), data, data)["result"]
        raw = self.evaluate(self.field(self.inventory, "Edit Fields", "body_raw"), data, data)["result"]
        self.assertEqual(target, "/api/internal/sofia/v1/assistant/query")
        self.assertEqual(json.loads(raw)["plan"], self.plan())
        request = {"target": target, "timestamp": "1794223979", "nonce": "test-nonce-0123456789",
                   "body_hash": hashlib.sha256(raw.encode()).hexdigest()}
        canonical = self.evaluate(self.field(self.inventory, "Edit Fields1", "canonical"), request)["result"]
        self.assertEqual(canonical.encode(), canonical_request("POST", target,
            request["timestamp"], request["nonce"], raw.encode()))
        legacy = {"resource": "aps"}
        target = self.evaluate(self.field(self.inventory, "Edit Fields", "target"), legacy, legacy)["result"]
        self.assertEqual(target, "/api/internal/sofia/v1/inventory/query")
        raw = self.evaluate(self.field(self.inventory, "Edit Fields", "body_raw"), legacy, legacy)["result"]
        self.assertEqual(json.loads(raw), legacy)

    def test_query_path_is_mandatory_and_scope_is_fixed(self):
        branches = self.main["connections"]["Encaminhar plano"]["main"]
        self.assertEqual(branches[0][0]["node"], "Executar consulta autorizada")
        query = next(node for node in self.main["nodes"] if node["name"] == "Executar consulta autorizada")
        values = query["parameters"]["workflowInputs"]["value"]
        self.assertEqual(query["parameters"]["workflowId"]["value"], self.inventory["id"])
        self.assertIn("$('Webhook')", values["sentinel_scope_token"])
        self.assertNotIn("fromAI", json.dumps(self.main))
        with self.assertRaises(ValueError):
            main, inventory = exports()
            main["pinData"] = {"Webhook": [{"token": "PRIVATE"}]}
            build_workflows(main, inventory)

    def test_every_expression_has_only_its_final_closing_delimiter(self):
        def walk(value):
            if isinstance(value, dict):
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
            elif isinstance(value, str) and value.startswith("={{"):
                self.assertNotIn("}}", value[3:-2], value[:100])

        walk(self.main)
        walk(self.inventory)
        with self.assertRaises(ValueError):
            expression("return {outer:{inner:1}};")
