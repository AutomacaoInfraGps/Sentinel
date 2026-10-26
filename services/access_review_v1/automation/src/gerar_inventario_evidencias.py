"""Converte as imagens do modelo em uma lista verificável de capturas novas."""

from __future__ import annotations

import csv
import difflib
import json
import re
import sys
import unicodedata
from pathlib import Path

from inspecionar_modelos import inspect


REGIONAL = [
    "Localização do grupo de suporte no ADUC",
    "Membros do grupo de suporte no ADUC",
    "Permissões delegadas e membros (script Allow na tela)",
    "Segurança avançada da OU mostrando a regra Deny do grupo de bloqueio",
    "Membros diretos do grupo de bloqueio (script Deny na tela)",
]
MATRIZ = [
    "Localização dos grupos Corporativo e Domain Admins",
    "Membros do GGS_Suporte_Corporativo",
    "Membros do Domain Admins",
    "Permissões delegadas do GGS_Suporte_Corporativo",
    "Permissões do Domain Admins",
    "Segurança avançada da OU Matriz mostrando a regra Deny do grupo de bloqueio",
    "Membros diretos do grupo de bloqueio da Matriz",
]
PREFIX = {
    7: "Server Manager: Dashboard do Rigel",
    8: "Server Manager: Local Server do Rigel",
    12: "Propriedades do Domain Admins: Membros",
    14: "Propriedades do Administrators: Membros",
    17: "Propriedades do Account Operators: Membros",
    25: "Advanced Security Settings da OU Regionais, parte 1",
    26: "Advanced Security Settings da OU Regionais, parte 2",
    28: "Advanced Security Settings da OU Regionais, parte 3",
    29: "Advanced Security Settings da OU Regionais, parte 4",
    30: "Advanced Security Settings da OU Regionais, parte 5",
    35: "Localização do GGS_Suporte_Corporativo",
    36: "Propriedades do GGS_Suporte_Corporativo: Membros",
    40: "dsacls da OU Regionais para GGS_Suporte_Corporativo",
    42: "Permissões especiais do GGS_Suporte_Corporativo",
    46: "Localização do GGS_Computadores_Dominio",
    48: "Propriedades do GGS_Computadores_Dominio: Membros",
    51: "Usuários dos grupos de apoio, parte 1",
    52: "Usuários dos grupos de apoio, parte 2",
    56: "Permissões delegadas do GGS_Computadores_Dominio",
    58: "Permissões especiais do GGS_Computadores_Dominio",
}
SUPPORT_OVERRIDES = {"OU São_Paulo / OU Praia Grande": ["GGS_Suporte_PraiaGrande"]}
OU_ALIASES = {"parana": "Curitiba"}
DENY_IMAGE_OVERRIDES = {
    "OU São_Paulo / OU Campseg": ["GGS_Bloqueio_OU_Campinas"],
    "OU São_Paulo / OU GR_Santana_de_Parnaiba": ["GGS_Bloqueio_GR_Santana_de_Parnaiba"],
}
CODE_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__import__("os").environ["SENTINEL_ACCESS_REVIEW_HOME"])
OMITTED_SLOTS = {"p028_1", "p029_1", "p030_1"}


def canonical(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(ch)).replace(" ", "_")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Uso: python src/gerar_inventario_evidencias.py modelo.docx coleta.json")
    model = inspect(Path(sys.argv[1]))
    collection = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8-sig"))
    known = {canonical(group["Nome"]) for group in collection["Grupos"]}
    paragraphs = model["paragrafos"]
    slots = []
    omitted_slots = []
    section = "Rede Galaxia e grupos principais"
    regional_start = None
    regional_image = 0
    last_label = ""
    for paragraph in paragraphs:
        if paragraph["texto"].strip():
            last_label = paragraph["texto"].strip()
        if paragraph["estilo"] == "Ttulo2" and paragraph["texto"].startswith("OU "):
            section = paragraph["texto"].rstrip(".")
            regional_start = paragraph["indice"]
            regional_image = 0
        for number, _ in enumerate(paragraph["imagens"], 1):
            index = paragraph["indice"]
            if regional_start is None:
                description = PREFIX.get(index, "Captura do bloco inicial a classificar")
            else:
                regional_image += 1
                labels = MATRIZ if "Matriz" in section else REGIONAL
                description = labels[regional_image - 1] if regional_image <= len(labels) else "Captura extra a classificar"
            key = f"p{index:03}_{number}"
            if key in OMITTED_SLOTS:
                omitted_slots.append(key)
                continue
            target = Path("dados/evidencias/ServidoresWindows") / f"{key}.png"
            slots.append({
                "slot": key,
                "secao": section,
                "descricao": description,
                "legenda_modelo": last_label,
                "arquivo_esperado": str(target),
                "status": "capturada" if (ROOT / target).is_file() else "pendente",
            })

    sections = []
    ous = collection["OUs"]
    starts = [i for i, x in enumerate(paragraphs) if x["estilo"] == "Ttulo2" and x["texto"].startswith("OU ")]
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(paragraphs)
        text = "\n".join(x["texto"] for x in paragraphs[start:end])
        support = list(dict.fromkeys(re.findall(r"GGS_Suporte_[\w&]+", text)))
        support = SUPPORT_OVERRIDES.get(paragraphs[start]["texto"].rstrip("."), support)
        deny = list(dict.fromkeys(re.findall(r"GGS_Bloqueio_OU_[\w&]+", text)))
        title = paragraphs[start]["texto"].rstrip(".")
        effective_deny = DENY_IMAGE_OVERRIDES.get(title, deny)
        leaf = paragraphs[start]["texto"].rstrip(".").split(" / OU ")[-1].removeprefix("OU ")
        expected_ou = OU_ALIASES.get(canonical(leaf), leaf)
        matches = [ou for ou in ous if canonical(ou["Nome"]) == canonical(expected_ou)]
        if matches:
            # Pode existir uma OU técnica com o mesmo nome dentro de Departamentos.
            # A seção auditável é a ocorrência mais próxima da raiz Regionais.
            menor_profundidade = min(ou["DN"].count(",") for ou in matches)
            matches = [ou for ou in matches if ou["DN"].count(",") == menor_profundidade]
        deny_acl = sorted({
            rule["Principal"].split("\\")[-1]
            for ou in matches for rule in ou["Regras"]
            if rule["Tipo"] == "Deny" and rule["Principal"].split("\\")[-1].casefold().startswith("ggs_bloqueio_")
        })
        sections.append({
            "secao": title,
            "ou_atual_encontrada": bool(matches),
            "ou_atual": [ou["DN"] for ou in matches],
            "grupos_suporte_modelo": support,
            "grupos_suporte_ausentes_no_ad": [x for x in support if canonical(x) not in known],
            "grupos_bloqueio_modelo": deny,
            "grupos_bloqueio_na_imagem_modelo": effective_deny,
            "grupos_bloqueio_ausentes_no_ad": [x for x in effective_deny if canonical(x) not in known and canonical(x) not in {canonical(y) for y in deny_acl}],
            "grupos_bloqueio_sem_detalhes_na_coleta": [x for x in effective_deny if canonical(x) not in known],
            "grupos_bloqueio_na_acl_atual": deny_acl,
        })

    output = ROOT / "dados/execucoes/Inventario-Evidencias-ServidoresWindows"
    output.parent.mkdir(exist_ok=True)
    output.with_suffix(".json").write_text(
        json.dumps({"total_slots": len(slots), "slots": slots, "slots_omitidos": omitted_slots, "secoes": sections}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with output.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(slots[0]))
        writer.writeheader()
        writer.writerows(slots)
    print(f"Seções regionais: {len(sections)}; imagens exigidas: {len(slots)}; capturadas: {sum(x['status']=='capturada' for x in slots)}")
    for item in sections:
        if item["grupos_suporte_ausentes_no_ad"] or item["grupos_bloqueio_ausentes_no_ad"] or item["grupos_bloqueio_sem_detalhes_na_coleta"] or not item["ou_atual_encontrada"]:
            print("REVISAR", item["secao"], "| OU atual:", item["ou_atual_encontrada"], "| suporte ausente:", ", ".join(item["grupos_suporte_ausentes_no_ad"]), "| bloqueio do modelo ausente:", ", ".join(item["grupos_bloqueio_ausentes_no_ad"]), "| Deny na ACL:", ", ".join(item["grupos_bloqueio_na_acl_atual"]))
            if item["grupos_bloqueio_sem_detalhes_na_coleta"]:
                print("  grupos sem membros coletados:", ", ".join(item["grupos_bloqueio_sem_detalhes_na_coleta"]))
            for absent in item["grupos_suporte_ausentes_no_ad"] + item["grupos_bloqueio_ausentes_no_ad"]:
                print("  possíveis nomes atuais:", ", ".join(difflib.get_close_matches(canonical(absent), sorted(known), n=3, cutoff=0.55)))


if __name__ == "__main__":
    main()
