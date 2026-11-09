"""Build private n8n update candidates from the operator's existing exports."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import urlsplit
import uuid

from sofia.query_response import FIELD_LABELS, RESOURCE_LABELS, STATUS_LABELS


ROOT = Path(__file__).resolve().parent
REGISTER_PATH = "/api/internal/sofia/v1/executions/register"
QUERY_PATH = "/api/internal/sofia/v1/assistant/query"
CANONICAL_EXPRESSION = "={{ ['POST', $json.target, $json.timestamp, $json.nonce, $json.body_hash].join(" + json.dumps("\n") + ") }}"


def plan_schema():
    properties = {
        "mode": {"type": "string", "enum": ["query", "chat", "clarify", "unsupported"]},
        "reply": {"type": "string", "maxLength": 500},
        "resource": {"type": "string", "enum": ["", *RESOURCE_LABELS]},
        "regional": {"type": "string", "maxLength": 120},
        "status": {"type": "string", "enum": ["", *STATUS_LABELS]},
        "search": {"type": "string", "maxLength": 120},
        "view": {"type": "string", "enum": ["count", "list", "detail"]},
        "fields": {"type": "array", "maxItems": 8, "items": {"type": "string", "enum": list(FIELD_LABELS)}},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        "offset": {"type": "integer", "minimum": 0, "maximum": 10000},
    }
    return {"type": "object", "additionalProperties": False,
            "properties": properties, "required": list(properties)}


def expression(code):
    return "={{ (() => {\n" + code + "\n})() }}"


def assignment(name, value, kind="string"):
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "sofia-field:" + name)),
            "name": name, "type": kind, "value": value}


def node(name, kind, parameters, position, version=1, credentials=None):
    result = {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "sofia-node:" + name)),
              "name": name, "type": kind, "typeVersion": version,
              "parameters": parameters, "position": position}
    if credentials:
        result["credentials"] = deepcopy(credentials)
    return result


def set_node(name, fields, position):
    return node(name, "n8n-nodes-base.set", {"assignments": {"assignments": fields}, "options": {}}, position, 3.5)


def connect(connections, source, target, output=0):
    branches = connections.setdefault(source, {}).setdefault("main", [])
    while len(branches) <= output:
        branches.append([])
    branches[output].append({"node": target, "type": "main", "index": 0})


def build_workflows(main_export, inventory_export):
    if main_export.get("pinData") or inventory_export.get("pinData"):
        raise ValueError("Remova dados fixados dos exports antes de gerar os candidatos.")
    main, inventory = deepcopy(main_export), deepcopy(inventory_export)
    originals = {item["name"]: item for item in main["nodes"]}
    register = originals["Registrar execução no Sentinel"]
    url = urlsplit(register["parameters"]["url"])
    if (url.scheme != "https" or url.username or url.password
            or url.path != REGISTER_PATH or url.query or url.fragment):
        raise ValueError("Origem HTTPS do Sentinel inválida no export.")
    origin = f"{url.scheme}://{url.netloc}"
    memory_credentials = originals["Memória Principal V3"]["credentials"]
    schema = plan_schema()
    validator = (ROOT / "validate_plan.js").read_text(encoding="utf-8").replace(
        "SCHEMA_PLACEHOLDER", json.dumps(schema, ensure_ascii=False))
    prompt = (ROOT / "plan_prompt.txt").read_text(encoding="utf-8")
    session_key = "$('Webhook').first().json.body.conversation_id + ':v4'"

    # Preserve the authenticated webhook and the execution registration chain.
    keep = ["Webhook", "Crypto", "Edit Fields", "Crypto2", "Edit Fields1", "Crypto1", register["name"]]
    nodes = [deepcopy(originals[name]) for name in keep]
    for index, item in enumerate(nodes):
        item["position"] = [index * 220, 0]
    canonical = next(item for item in nodes if item["name"] == "Edit Fields1")
    canonical["parameters"]["assignments"]["assignments"][0]["value"] = CANONICAL_EXPRESSION

    nodes.append(node("Verificar cancelamento", "n8n-nodes-base.if", {
        "conditions": {"options": {"caseSensitive": True, "typeValidation": "strict", "version": 2},
                       "conditions": [{"id": "cancelled", "leftValue": "={{ $json.cancelled }}",
                                       "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
                       "combinator": "and"}, "options": {}}, [1540, 0], 2.2))
    nodes.append(set_node("Consulta cancelada", [assignment("reply", "Consulta cancelada.")], [1760, -260]))
    memory_sql = """SELECT jsonb_build_object(
 'previous_query', (SELECT message->'sofia_query' FROM sofia_memory.sofia_chat_history
   WHERE session_id=$1 AND message ? 'sofia_query' AND message->'sofia_query' <> 'null'::jsonb
   ORDER BY id DESC LIMIT 1),
 'recent_messages', COALESCE((SELECT jsonb_agg(jsonb_build_object(
   'role', message->>'type', 'text', left(message->'data'->>'content',240)) ORDER BY id)
   FROM (SELECT id,message FROM sofia_memory.sofia_chat_history WHERE session_id=$1
     AND (message->>'type'='human' OR message->>'sofia_kind' IN ('chat','clarify','unsupported'))
     ORDER BY id DESC LIMIT 4) recent),'[]'::jsonb)) AS context;"""
    nodes.append(node("Ler contexto curto", "n8n-nodes-base.postgres", {
        "operation": "executeQuery", "query": memory_sql,
        "options": {"queryReplacement": "={{ [" + session_key + "] }}"}}, [1760, 0], 2.6, memory_credentials))
    # JSON syntax is also JavaScript syntax; input and history are encoded as data.
    config = json.dumps({"model": originals["Ollama Operacional"]["parameters"]["model"],
        "stream": False, "think": False, "format": schema,
        "options": {"num_ctx": 4096, "num_thread": 8, "num_predict": 384, "temperature": 0}}, ensure_ascii=False)
    body = expression("const input = $('Webhook').first().json.body;\nconst config = " + config + ";\n" +
        "config.messages = [{role:'system',content:" + json.dumps(prompt, ensure_ascii=False) + "}," +
        "{role:'user',content:JSON.stringify({user_context:input.user_context," +
        "context:$json.context,message:input.message})}];\nreturn JSON.stringify(config);")
    nodes.append(node("Interpretar pedido", "n8n-nodes-base.httpRequest", {
        "method": "POST", "url": "http://ollama:11434/api/chat", "sendBody": True,
        "contentType": "raw", "rawContentType": "application/json", "body": body,
        "options": {"timeout": 480000}}, [1980, 0], 4.5))
    nodes.append(set_node("Validar plano", [assignment("plan", expression(validator), "object")], [2200, 0]))
    nodes.append(node("Encaminhar plano", "n8n-nodes-base.switch", {
        "rules": {"values": [{"conditions": {
            "options": {"caseSensitive": True, "typeValidation": "strict", "version": 2},
            "conditions": [{"id": "query", "leftValue": "={{ $json.plan.mode }}", "rightValue": "query",
                            "operator": {"type": "string", "operation": "equals"}}], "combinator": "and"},
            "renameOutput": True, "outputKey": "consulta"}]},
        "options": {"fallbackOutput": "extra"}}, [2420, 0], 3.3))
    inputs = {"mappingMode": "defineBelow", "value": {
        "sentinel_scope_token": "={{ $('Webhook').first().json.body.sentinel_scope_token }}",
        "plan": "={{ $json.plan }}"}, "matchingColumns": [],
        "schema": [{"id": name, "displayName": name, "required": False, "display": True,
                    "type": kind, "canBeUsedToMatch": True} for name, kind in
                   [("sentinel_scope_token", "string"), ("plan", "object")]],
        "attemptToConvertTypes": False, "convertFieldsToString": False}
    nodes.append(node("Executar consulta autorizada", "n8n-nodes-base.executeWorkflow", {
        "workflowId": {"__rl": True, "value": inventory["id"], "mode": "id"},
        "workflowInputs": inputs, "options": {"waitForSubWorkflow": True}}, [2640, -100], 1.3))
    nodes.append(set_node("Resposta de conversa", [assignment("reply", "={{ $json.plan.reply }}")], [2640, 160]))
    nodes.append(set_node("Preparar resposta", [assignment("reply", "={{ $json.reply }}"),
        assignment("plan", "={{ $('Validar plano').first().json.plan }}", "object"),
        assignment("page", "={{ {next_offset: $json.next_offset ?? null} }}", "object")], [2860, 0]))
    store_sql = """WITH inserted AS (
 INSERT INTO sofia_memory.sofia_chat_history(session_id,message)
 VALUES ($1,$2::jsonb),($1,$3::jsonb) RETURNING id
) SELECT count(*) AS saved FROM inserted;"""
    values = "={{ [" + session_key + ", JSON.stringify({type:'human',data:{content:$('Webhook').first().json.body.message}}), " + \
        "JSON.stringify({type:'ai',data:{content:$json.reply},sofia_kind:$json.plan.mode," + \
        "sofia_query:$json.plan.mode==='query'?{...$json.plan,next_offset:$json.page.next_offset}:null})] }}"
    nodes.append(node("Guardar conversa", "n8n-nodes-base.postgres", {"operation": "executeQuery",
        "query": store_sql, "options": {"queryReplacement": values}}, [3080, 0], 2.6, memory_credentials))
    nodes.append(set_node("Entregar resposta", [assignment("reply", "={{ $('Preparar resposta').first().json.reply }}")], [3300, 0]))
    respond = deepcopy(originals["Respond to Webhook"])
    respond["position"] = [3520, 0]
    nodes.append(respond)
    connections = {}
    chain = keep + ["Verificar cancelamento"]
    for source, target in zip(chain, chain[1:]):
        connect(connections, source, target)
    connect(connections, "Verificar cancelamento", "Consulta cancelada", 0)
    connect(connections, "Consulta cancelada", respond["name"])
    connect(connections, "Verificar cancelamento", "Ler contexto curto", 1)
    chain = ["Ler contexto curto", "Interpretar pedido", "Validar plano", "Encaminhar plano"]
    for source, target in zip(chain, chain[1:]):
        connect(connections, source, target)
    connect(connections, "Encaminhar plano", "Executar consulta autorizada", 0)
    connect(connections, "Encaminhar plano", "Resposta de conversa", 1)
    for source in ("Executar consulta autorizada", "Resposta de conversa"):
        connect(connections, source, "Preparar resposta")
    for source, target in zip(["Preparar resposta", "Guardar conversa", "Entregar resposta"],
                              ["Guardar conversa", "Entregar resposta", respond["name"]]):
        connect(connections, source, target)
    main.update(nodes=nodes, connections=connections, pinData={}, active=False)

    # The subworkflow accepts both the existing inventory contract and a new plan.
    trigger = next(item for item in inventory["nodes"] if item["type"].endswith("executeWorkflowTrigger"))
    fields = trigger["parameters"]["workflowInputs"]["values"]
    if not any(field["name"] == "plan" for field in fields):
        fields.append({"name": "plan", "type": "object"})
    trigger_ref = "$('" + trigger["name"] + "').first().json"
    edit = next(item for item in inventory["nodes"] if item["name"] == "Edit Fields")
    for field in edit["parameters"]["assignments"]["assignments"]:
        if field["name"] == "target":
            field["value"] = "={{ " + trigger_ref + ".plan?.mode === 'query' ? '" + QUERY_PATH + "' : '/api/internal/sofia/v1/inventory/query' }}"
        elif field["name"] == "body_raw":
            original = field["value"]
            field["value"] = expression("const input = " + trigger_ref + ";\n" +
                "if (input.plan?.mode === 'query') return JSON.stringify({sentinel_scope_token:input.sentinel_scope_token,plan:input.plan});\n" +
                "return " + original.removeprefix("={{").removesuffix("}}").strip() + ";")
    canonical = next(item for item in inventory["nodes"] if item["name"] == "Edit Fields1")
    canonical["parameters"]["assignments"]["assignments"][0]["value"] = CANONICAL_EXPRESSION
    http = next(item for item in inventory["nodes"] if item["type"].endswith("httpRequest"))
    http["parameters"]["url"] = "={{ " + json.dumps(origin) + " + $json.target }}"
    inventory.update(active=False, pinData={})
    # Omit instance ownership metadata from candidates; keep stable workflow IDs.
    keys = {"id", "name", "nodes", "connections", "settings", "active", "pinData"}
    return ({key: value for key, value in main.items() if key in keys},
            {key: value for key, value in inventory.items() if key in keys})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("instance/sofia-workflows"))
    args = parser.parse_args()
    candidates = build_workflows(json.loads(args.main.read_text(encoding="utf-8-sig")),
                                json.loads(args.inventory.read_text(encoding="utf-8-sig")))
    args.output.mkdir(parents=True, exist_ok=True)
    for filename, workflow in zip(("sofia-main-controlled.json", "sofia-inventory-controlled.json"), candidates):
        (args.output / filename).write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(args.output / filename)


if __name__ == "__main__":
    main()
