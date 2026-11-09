import hashlib
import json
import shutil
import subprocess
import unittest

from sofia.n8n.build_readonly_workflows import build_workflows, plan_schema
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
        runner = r"""
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const lookup = () => ({first: () => ({json:input.inputs})});
try {
  const result = new Function('$json', '$', 'return (' + input.code.slice(3,-2) + ');')(input.data,lookup);
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
            {"body": {"message": "Quais APs?", "user_context": {"display_name": "Teste"},
                      "sentinel_scope_token": "PRIVATE_SCOPE", "allowed_regionals": ["PRIVATE_REGION"]}})
        body = json.loads(result["result"])
        self.assertEqual(body["format"], plan_schema())
        self.assertEqual(body["options"]["num_thread"], 8)
        self.assertNotIn("PRIVATE_SCOPE", str(body))
        self.assertNotIn("PRIVATE_REGION", str(body))

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
