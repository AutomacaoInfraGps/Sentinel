"""Validate license arguments with existing Set/IF nodes, without enabling Code."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import uuid

from .build_agent_workflow import TOOL_TYPE, _find, _tool_plan, tool_validation_code
from .build_readonly_workflows import assignment, connect, expression, node, set_node


BRIDGE_ID = uuid.uuid5(uuid.NAMESPACE_URL, "sofia:license-tool-validation:v1").hex[:16]
BRIDGE_NAME = "SofIA Tool - Validar consulta de licencas"
CONTEXT_EXPRESSION = "={{ ({message:$('Webhook').first().json.body.message, allowed_regionals:$('Webhook').first().json.body.allowed_regionals}) }}"


def validation_code():
    rules = tool_validation_code("licenses").replace(
        "const regionalInput = $('Webhook').first().json.body;",
        "const regionalInput = input.request_context;")
    return """const input = $json;
try {
  if (!input.plan || typeof input.plan !== 'object' || Array.isArray(input.plan)) throw new Error('Plano ausente ou invalido.');
  const plan = {...input.plan};
  const keys = ['mode','reply','resource','regional','status','search','view','fields','limit','offset'];
  if (Object.keys(plan).some(key => !keys.includes(key)) || plan.mode !== 'query' || plan.reply !== '') throw new Error('Contrato de consulta invalido.');
  if (typeof input.sentinel_scope_token !== 'string' || !input.sentinel_scope_token) throw new Error('Escopo autenticado ausente.');
  if (!input.request_context || typeof input.request_context.message !== 'string' || !Array.isArray(input.request_context.allowed_regionals)) throw new Error('Contexto autenticado ausente.');
""" + rules + """
  return {valid:true, sentinel_scope_token:input.sentinel_scope_token, plan};
} catch (error) {
  return {valid:false, response:{success:false, mode:'read-only',
    error_code:'INVALID_TOOL_ARGUMENTS',
    reply:'Consulta nao executada: ' + error.message + ' Corrija os argumentos e tente novamente. Nao interprete esta falha como ausencia de registros.'} };
}
"""


def build_bridge(current):
    tool = _find(current, "Consultar licencas")
    if tool.get("type") != TOOL_TYPE:
        raise ValueError("Ferramenta de licencas inesperada.")
    authorized_id = tool["parameters"]["workflowId"]["value"]
    if not authorized_id or authorized_id == BRIDGE_ID:
        raise ValueError("Forneca o export que ainda referencia o subworkflow autorizado original.")
    trigger = node("Entrada da ferramenta", "n8n-nodes-base.executeWorkflowTrigger", {
        "workflowInputs": {"values": [
            {"name": "sentinel_scope_token", "type": "string"},
            {"name": "plan", "type": "object"},
            {"name": "request_context", "type": "object"}]}}, [0, 0], 1.1)
    validate = set_node("Validar argumentos", [
        assignment("validation", expression(validation_code()), "object")], [240, 0])
    branch = node("Argumentos validos", "n8n-nodes-base.if", {
        "conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
            "conditions": [{"id": "valid", "leftValue": "={{ $json.validation.valid }}", "rightValue": True,
                            "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
            "combinator": "and"}, "options": {}}, [480, 0], 2.2)
    execute = node("Consultar pelo fluxo autorizado", "n8n-nodes-base.executeWorkflow", {
        "workflowId": {"__rl": True, "value": authorized_id, "mode": "id"},
        "workflowInputs": {"mappingMode": "defineBelow", "value": {
            "sentinel_scope_token": "={{ $json.validation.sentinel_scope_token }}", "plan": "={{ $json.validation.plan }}"},
            "matchingColumns": [], "schema": [
                {"id": key, "displayName": key, "type": kind, "required": True, "display": True}
                for key, kind in (("sentinel_scope_token", "string"), ("plan", "object"))],
            "attemptToConvertTypes": False, "convertFieldsToString": False},
        "options": {"waitForSubWorkflow": True}}, [720, -100], 1.3)
    failure = set_node("Retornar erro de argumentos", [
        assignment("success", False, "boolean"),
        assignment("mode", "read-only"),
        assignment("error_code", "INVALID_TOOL_ARGUMENTS"),
        assignment("reply", "={{ $json.validation.response.reply }}")], [720, 140])
    connections = {}
    connect(connections, trigger["name"], validate["name"])
    connect(connections, validate["name"], branch["name"])
    connect(connections, branch["name"], execute["name"], 0)
    connect(connections, branch["name"], failure["name"], 1)
    bridge = {"id": BRIDGE_ID, "name": BRIDGE_NAME, "active": False, "pinData": {},
              "settings": {"executionOrder": "v1"},
              "nodes": [trigger, validate, branch, execute, failure], "connections": connections}
    update = deepcopy(current)
    update["active"] = False
    update["pinData"] = {}
    # Preserve the actual exported model, memory, authentication and all other tools.
    tool = _find(update, "Consultar licencas")
    tool["parameters"]["workflowId"] = {"__rl": True, "value": BRIDGE_ID, "mode": "id"}
    inputs = tool["parameters"]["workflowInputs"]
    scope = inputs["value"]["sentinel_scope_token"]
    inputs.update(value={"sentinel_scope_token": scope, "plan": _tool_plan("licenses", validate=False),
                         "request_context": CONTEXT_EXPRESSION},
                  schema=[{"id": key, "displayName": key, "type": kind, "required": True, "display": True}
                          for key, kind in (("sentinel_scope_token", "string"), ("plan", "object"),
                                            ("request_context", "object"))])
    for key in ("versionId", "activeVersionId", "activeVersion", "shared", "createdAt", "updatedAt"):
        update.pop(key, None)
    return bridge, update


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main", type=Path, required=True)
    parser.add_argument("--expected-id", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("instance/sofia-workflows"))
    args = parser.parse_args()
    raw = args.main.read_bytes()
    current = json.loads(raw.decode("utf-8-sig"))
    if current.get("id") != args.expected_id or current.get("pinData"):
        raise ValueError("ID divergente ou dados fixados no export.")
    bridge, update = build_bridge(current)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    backup = args.output_dir / ("sofia-main-before-license-bridge-" + hashlib.sha256(raw).hexdigest()[:12] + ".json")
    if backup.exists() and backup.read_bytes() != raw:
        raise ValueError("Backup existente divergente.")
    backup.write_bytes(raw)
    for filename, value in (("sofia-license-validation-tool.json", bridge),
                            ("sofia-main-license-bridge-update.json", update)):
        path = args.output_dir / filename
        if path.resolve() == args.main.resolve():
            raise ValueError("Destino nao pode sobrescrever o export de origem.")
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(path)
    print(backup)


if __name__ == "__main__":
    main()
