"""Build a local AI Agent draft or an explicit update of an existing n8n workflow."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
import uuid

from sofia.n8n_client import MAX_REPLY_LENGTH
from sofia.query_response import FIELD_LABELS, RESOURCE_LABELS
from .build_readonly_workflows import REGISTER_PATH, assignment, connect, expression, node, set_node


ROOT = Path(__file__).resolve().parent
AGENT = "SofIA - Agente Local"
TOOL_TYPE = "@n8n/n8n-nodes-langchain.toolWorkflow"
PREFIX = ["Webhook", "Crypto", "Edit Fields", "Crypto2", "Edit Fields1", "Crypto1",
          "Registrar execução no Sentinel", "Verificar cancelamento", "Consulta cancelada"]


def _find(workflow, name):
    matches = [item for item in workflow.get("nodes", []) if item.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"No esperado ausente ou duplicado: {name}")
    return matches[0]


def _ai(key, description, kind="string", default=""):
    return "$fromAI(" + ", ".join(json.dumps(value, ensure_ascii=False)
                                 for value in (key, description, kind, default)) + ")"


def _tool_plan(resource=None, *, validate=True):
    resources = [name for name in RESOURCE_LABELS if name not in {"alerts", "licenses"}]
    permitted_fields = {
        "alerts": ["name", "regional", "status", "category", "quantity"],
        "licenses": ["name", "regional", "status", "firewall", "firewall_serial", "expires_at", "days_remaining"],
    }.get(resource, list(FIELD_LABELS))
    value = json.dumps(resource) if resource else _ai(
        "resource", "Tipo de inventario solicitado. Valores permitidos: " + ", ".join(resources))
    state_help = {
        "alerts": "Severidade solicitada: critical, high, medium ou attention. Sem restricao e para todas as severidades use vazio. Ativo nao e severidade.",
        "licenses": "Estado solicitado: expiring, expired, valid ou unavailable. Sem restricao use vazio.",
    }.get(resource, "Estado solicitado: online, offline, warning, inactive, maintenance ou unknown. Sem restricao use vazio.")
    search_help = ("Categoria de equipamento em singular ou nome especifico do alerta. Nao inclua regional, estado ou severidade. Sem restricao use vazio."
                   if resource == "alerts" else
                   "Nome ou produto especifico. Nao repita o tipo de inventario, a regional, o estado nem os atributos. Sem busca adicional use vazio.")
    code = "const plan = {mode:'query', reply:'',\nresource:" + value + ",\n"
    parameters = {
        "regional": _ai("regional", "Codigo ou nome de uma regional mencionada ou retomada. Vazio para todas as autorizadas."),
        "status": _ai("status", state_help),
        "search": _ai("search", search_help),
        "view": _ai("view", "count para quantidade de itens ou resumo; list para identificar itens e seus atributos, incluindo dias restantes; detail para detalhes ampliados.", default="list"),
        "fields": _ai("fields", "Array JSON apenas de atributos pedidos. Vazio para padroes. Campos disponiveis: "
                      + ", ".join(f"{key} ({FIELD_LABELS[key]})" for key in permitted_fields), "json", []),
        "limit": _ai("limit", "Itens por pagina, inteiro de 1 a 50. Padrao 20.", "number", 20),
        "offset": _ai("offset", "Inicio da pagina. Inteiro de 0 a 10000. Primeira pagina 0; continuacao usa next_offset da ferramenta.", "number", 0),
    }
    code += ",\n".join(f"{key}:{parameter}" for key, parameter in parameters.items()) + "\n};\n"
    if not validate:
        return expression(code + "return plan;")
    return expression(code + tool_validation_code(resource) + "\nreturn plan;")


def tool_validation_code(resource):
    resources = [name for name in RESOURCE_LABELS if name not in {"alerts", "licenses"}]
    permitted_fields = {
        "alerts": ["name", "regional", "status", "category", "quantity"],
        "licenses": ["name", "regional", "status", "firewall", "firewall_serial", "expires_at", "days_remaining"],
    }.get(resource, list(FIELD_LABELS))
    # Validate transport types before resolving exact regional aliases from trusted metadata.
    code = "const resources = " + json.dumps([resource] if resource else resources) + ";\n"
    code += "const states = " + json.dumps({
        "alerts": ["critical", "high", "medium", "attention"],
        "licenses": ["expiring", "expired", "valid", "unavailable"],
    }.get(resource, ["online", "offline", "warning", "inactive", "maintenance", "unknown"])) + ";\n"
    code += "const fields = " + json.dumps(permitted_fields) + ";\n"
    code += """if (!resources.includes(plan.resource) || !['count','list','detail'].includes(plan.view)) throw new Error('Recurso ou apresentacao invalida.');
if (!Array.isArray(plan.fields) || plan.fields.length > 8 || plan.fields.some(field => !fields.includes(field))) throw new Error('Campos invalidos.');
for (const key of ['regional','status','search']) {
  if (typeof plan[key] !== 'string' || plan[key].length > 120) throw new Error('Filtro invalido.');
}
if (plan.status && !states.includes(plan.status)) throw new Error('Estado ou severidade invalido.');
if (plan.view === 'count' && plan.fields.some(field => !['name','regional','status'].includes(field))) throw new Error('Atributos de itens exigem list ou detail.');
if (!Number.isInteger(plan.limit) || plan.limit < 1 || plan.limit > 50 || !Number.isInteger(plan.offset) || plan.offset < 0 || plan.offset > 10000) throw new Error('Paginacao invalida.');
"""
    code += (ROOT / "resolve_tool_regional.js").read_text(encoding="utf-8")
    return code


def export_tool_expressions(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, resource in (("alertas", "alerts"), ("licencas", "licenses"), ("inventario", None)):
        path = output / f"consultar-{name}-plan-expression.txt"
        path.write_text(_tool_plan(resource).removeprefix("=").strip() + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def _wire(connections, source, target, kind):
    connections.setdefault(source, {})[kind] = [[{"node": target, "type": kind, "index": 0}]]


def build_agent_workflow(current, inventory, previous, *, model=None, update_existing=False, expected_id=None):
    if update_existing and (not expected_id or current.get("id") != expected_id):
        raise ValueError("Confirme explicitamente o ID do workflow que sera atualizado.")
    for workflow in (current, inventory, previous):
        if workflow.get("pinData"):
            raise ValueError("Remova dados fixados antes de gerar o candidato.")
    original = deepcopy(current)
    url = urlsplit(_find(original, PREFIX[6])["parameters"]["url"])
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.path != REGISTER_PATH or url.query or url.fragment:
        raise ValueError("Origem de registro invalida.")
    selected = _find(original, "Executar consulta autorizada")["parameters"]["workflowId"]["value"]
    if selected != inventory.get("id"):
        raise ValueError("O subworkflow fornecido nao e o referenciado pelo fluxo atual.")
    trigger = next((item for item in inventory["nodes"] if item["type"].endswith("executeWorkflowTrigger")), None)
    inputs = trigger and trigger.get("parameters", {}).get("workflowInputs", {}).get("values", [])
    if not any(item.get("name") == "plan" and item.get("type") == "object" for item in inputs):
        raise ValueError("Subworkflow deve aceitar plan como objeto.")
    # Credential references come from supplied exports. No secrets are read or copied from executions.
    memory_credentials = _find(original, "Ler contexto curto").get("credentials", {})
    llm = deepcopy(_find(previous, "Ollama Operacional"))
    if not memory_credentials.get("postgres") or not llm.get("credentials", {}).get("ollamaApi"):
        raise ValueError("Referencias de credenciais locais ausentes.")
    llm.update(name="Ollama Local", position=[1780, 260])
    selected_model = model or llm["parameters"].get("model")
    if selected_model not in {"qwen3:4b-instruct", "qwen3:4b", "qwen3:8b", "qwen3:1.7b"}:
        raise ValueError("Escolha um dos modelos locais ja instalados.")
    llm["parameters"]["model"] = selected_model
    llm["parameters"]["options"] = {**llm["parameters"].get("options", {}),
        "think": False, "numCtx": 8192, "numPredict": 2048}

    nodes = [deepcopy(_find(original, name)) for name in PREFIX]
    webhook = nodes[0]
    if not update_existing:
        webhook["parameters"]["path"] = "sofia-agent-lab-" + uuid.uuid4().hex
        webhook["webhookId"] = str(uuid.uuid4())
    prompt = (ROOT / "agent_prompt.txt").read_text(encoding="utf-8")
    system = expression("const input = $('Webhook').first().json.body;\n"
        "const identity = input.user_context ?? {};\n"
        "return " + json.dumps(prompt, ensure_ascii=False) + " + '\\n\\nIDENTIDADE AUTENTICADA\\n' + JSON.stringify({"
        "display_name:identity.display_name ?? 'Usuario',relationship:identity.relationship === 'creator' ? 'creator' : 'user',"
        "allowed_regionals:Array.isArray(input.allowed_regionals) ? input.allowed_regionals : []});")
    agent = node(AGENT, "set", {}, [1980, 0])
    agent.update(type="@n8n/n8n-nodes-langchain.agent", typeVersion=3.1,
                 parameters={"promptType": "define", "text": "={{ $('Webhook').first().json.body.message }}",
                             "needsFallback": False, "options": {
                                 "systemMessage": system, "maxIterations": 6, "returnIntermediateSteps": True}})
    memory_suffix = ":agent-v1" if update_existing else ":agent-lab-v1"
    memory = node("Memoria Agente Local", "set", {}, [1980, 260])
    memory.update(type="@n8n/n8n-nodes-langchain.memoryPostgresChat", typeVersion=1.4,
                  parameters={"sessionIdType": "customKey", "sessionKey": expression(
                      "const key = $('Webhook').first().json.body.conversation_id;\n"
                      "if (typeof key !== 'string' || !/^[a-f0-9]{64}$/.test(key)) throw new Error('Sessao autenticada ausente.');\n"
                      "return key + " + json.dumps(memory_suffix) + ";"),
                      "tableName": "sofia_chat_history", "contextWindowLength": 4},
                  credentials=deepcopy(memory_credentials))
    nodes.extend([agent, llm, memory])
    tools = [
        ("Consultar alertas atuais", "alerts", "Le ocorrencias de alertas atuais em todas as categorias. Equipamento citado qualifica search. Nao usar inventario para responder alertas. Sem severidade solicitada use status vazio."),
        ("Consultar licencas", "licenses", "Le validade e estados das licencas. Dias ate vencer usa fields=[days_remaining] e view=list, nao count. Regional vai somente em regional, nao em search."),
        ("Consultar inventario operacional", None, "Le firewalls, links, vpns, servers, aps, switches, wifi e regionals. Nao consulta ocorrencias de alertas nem licencas; use as ferramentas especificas para esses assuntos."),
    ]
    for index, (name, resource, description) in enumerate(tools):
        tool = node(name, "set", {}, [2200 + 240 * index, 260])
        tool.update(type=TOOL_TYPE, typeVersion=2.2, parameters={
            "description": description + " A resposta contem success, reply, query, matched, displayed, next_offset, fresh e updated_at no nivel principal. O escopo e imposto pelo Sentinel.",
            "workflowId": {"__rl": True, "value": selected, "mode": "id"},
            "workflowInputs": {"mappingMode": "defineBelow", "value": {
                "sentinel_scope_token": "={{ $('Webhook').first().json.body.sentinel_scope_token }}",
                "plan": _tool_plan(resource)}, "matchingColumns": [], "schema": [
                    {"id": key, "displayName": key, "type": kind, "required": True,
                     "display": True, "canBeUsedToMatch": True}
                    for key, kind in (("sentinel_scope_token", "string"), ("plan", "object"))],
                "attemptToConvertTypes": False, "convertFieldsToString": False}})
        nodes.append(tool)
    nodes.append(set_node("Preparar resposta agente", [assignment("reply", expression(
        "const reply = $json.output;\nif (typeof reply !== 'string' || !reply.trim() || reply.length > "
        + str(MAX_REPLY_LENGTH) + ") throw new Error('Resposta do agente invalida.');\nreturn reply;"))], [2240, 0]))
    nodes.append(deepcopy(_find(original, "Respond to Webhook")))
    connections = {}
    for source, target in zip(PREFIX[:8], PREFIX[1:8]):
        connect(connections, source, target)
    connect(connections, "Verificar cancelamento", "Consulta cancelada", 0)
    connect(connections, "Verificar cancelamento", AGENT, 1)
    connect(connections, "Consulta cancelada", "Respond to Webhook")
    connect(connections, AGENT, "Preparar resposta agente")
    connect(connections, "Preparar resposta agente", "Respond to Webhook")
    _wire(connections, llm["name"], AGENT, "ai_languageModel")
    _wire(connections, memory["name"], AGENT, "ai_memory")
    for name, _, _ in tools:
        _wire(connections, name, AGENT, "ai_tool")
    # An update preserves entry-point identity; an independent draft cannot replace production.
    original_ids = {item["name"]: item["id"] for item in original["nodes"]}
    for item in nodes:
        item["id"] = original_ids[item["name"]] if update_existing and item["name"] in original_ids else str(uuid.uuid4())
    result = {"name": original["name"] if update_existing else "SofIA - Agente Local - Homologacao",
              "active": False, "pinData": {}, "settings": deepcopy(original.get("settings", {})),
              "nodes": nodes, "connections": connections}
    if update_existing:
        result["id"] = original["id"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--model")
    parser.add_argument("--update-existing", action="store_true",
                        help="Prepara atualizacao do ID e webhook existentes; nao importa nem publica.")
    parser.add_argument("--expected-id", help="ID conferido do workflow atual, obrigatorio em --update-existing.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.update_existing and args.expected_id:
        parser.error("--expected-id requer --update-existing.")
    if args.output is None:
        filename = "sofia-main-agent-update.json" if args.update_existing else "sofia-agent-local-candidate.json"
        args.output = Path("instance/sofia-workflows") / filename
    if args.output.resolve() in {path.resolve() for path in (args.main, args.inventory, args.previous)}:
        raise ValueError("O arquivo de saida nao pode sobrescrever um export de origem.")
    def load(path):
        return json.loads(path.read_text(encoding="utf-8-sig"))
    workflow = build_agent_workflow(load(args.main), load(args.inventory), load(args.previous),
                                    model=args.model, update_existing=args.update_existing, expected_id=args.expected_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.update_existing:
        source = args.main.read_bytes()
        backup = args.output.parent / ("sofia-main-before-agent-" + hashlib.sha256(source).hexdigest()[:12] + ".json")
        if backup.exists():
            if backup.read_bytes() != source:
                raise ValueError("Backup existente diverge do export; nao sera sobrescrito.")
        else:
            with backup.open("xb") as stream:
                stream.write(source)
        print("Backup do export fornecido: " + str(backup))
    args.output.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    for path in export_tool_expressions(args.output.parent):
        print(path)
    if args.update_existing:
        print("Atualizacao preparada para " + workflow["id"] + ". ID, webhook e credenciais preservados. Importacao e publicacao sao manuais.")
    else:
        print("Candidato inativo, sem ID de producao. Homologacao exige configuracao propria do Sentinel. Nao publicar automaticamente.")


if __name__ == "__main__":
    main()
