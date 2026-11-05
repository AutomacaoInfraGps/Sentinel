"""Monta a auditoria de firewalls para qualquer quantidade de dispositivos."""
from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import render_auditoria_admanager as engine

W = engine.W
NS = engine.NS


def ptext(paragraph):
    return "".join((item.text or "") for item in paragraph.findall(".//w:t", NS)).strip()


def set_text(paragraph, value):
    texts = paragraph.findall(".//w:t", NS)
    if texts:
        texts[0].text = value
        for item in texts[1:]:
            item.text = ""
    else:
        run = ET.SubElement(paragraph, f"{{{W}}}r")
        ET.SubElement(run, f"{{{W}}}t").text = value


def users_summary(rows):
    found = []
    for row in rows:
        parts = row.split()
        if len(parts) < 4 or not parts[0].isdigit() or "Local" not in parts:
            continue
        local = parts.index("Local")
        if local > 1:
            found.append(f"{parts[1]} ({parts[local - 1]})")
    value = "; ".join(found) if found else "nenhum registro visível"
    return f"Usuários e permissões identificados: {value}."


def regional_headings(body):
    return [p for p in body.findall("w:p", NS) if re.match(r"^\d+\s+", ptext(p))]


def resize_regional_blocks(body, total):
    headings = regional_headings(body)
    if not headings:
        raise ValueError("O modelo não possui bloco regional para ser usado como base.")
    children = list(body)
    last_start = children.index(headings[-1])
    section = body.find("w:sectPr", NS)
    last_end = children.index(section) if section is not None else len(children)
    template = [copy.deepcopy(node) for node in children[last_start:last_end]]

    if total > len(headings):
        insertion = list(body).index(section) if section is not None else len(list(body))
        for _ in range(total - len(headings)):
            for node in template:
                body.insert(insertion, copy.deepcopy(node))
                insertion += 1
    elif total < len(headings):
        headings = regional_headings(body)
        for heading in reversed(headings[total:]):
            children = list(body)
            start = children.index(heading)
            later = [h for h in regional_headings(body) if h in children and children.index(h) > start]
            end = children.index(later[0]) if later else (children.index(section) if section is not None else len(children))
            for node in children[start:end]:
                body.remove(node)


def prepare_model(model, result, target):
    with zipfile.ZipFile(model) as source:
        payload = source.read("word/document.xml")
        namespaces = engine.namespace_map(payload)
        root = ET.fromstring(payload)
        entries = {name: source.read(name) for name in source.namelist()}
    body = root.find("w:body", NS)
    regionals = result.get("regionais", [])
    resize_regional_blocks(body, len(regionals))

    paragraphs = body.findall("w:p", NS)
    if len(paragraphs) > 1:
        set_text(paragraphs[1], re.sub(r"\b41\b", str(len(regionals)), ptext(paragraphs[1]), count=1))
    headings = regional_headings(body)
    slots = []
    for index, item in enumerate(regionals):
        heading = headings[index]
        set_text(heading, f"{index + 1} {item['dispositivo']}")
        paragraphs = body.findall("w:p", NS)
        start = paragraphs.index(heading)
        image_index = next(i for i in range(start + 1, len(paragraphs)) if paragraphs[i].find(".//a:blip", NS) is not None)
        narrative = [p for p in paragraphs[start + 1:image_index] if ptext(p)]
        if narrative:
            set_text(narrative[0], users_summary(item.get("administradores", [])))
            for paragraph in narrative[1:]:
                set_text(paragraph, "")
        slots.append(f"p{image_index:03}_1")

    entries["word/document.xml"] = engine.serialize_xml(root, namespaces)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as output:
        for name, data in entries.items():
            output.writestr(name, data)
    return slots


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("modelo", type=Path)
    parser.add_argument("evidencias", type=Path)
    parser.add_argument("saida", type=Path)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8-sig"))

    with tempfile.TemporaryDirectory() as folder_name:
        folder = Path(folder_name)
        prepared = folder / "modelo_atualizado.docx"
        regional_slots = prepare_model(args.modelo, result, prepared)
        evidence = folder / "evidencias"
        evidence.mkdir()
        base_slots = {"p005_1", "p008_1", "p014_1"}
        for slot in base_slots:
            shutil.copy2(args.evidencias / f"{slot}.png", evidence / f"{slot}.png")
        for item, slot in zip(result.get("regionais", []), regional_slots):
            source = args.evidencias / item["evidencia"]
            shutil.copy2(source, evidence / f"{slot}.png")
        engine.SLOTS = base_slots | set(regional_slots)
        rendered = engine.render(prepared, evidence, args.saida)

    rendered.update({"tipo": "Auditoria Galaxia Firewalls", "regionais": len(regional_slots)})
    print(json.dumps(rendered, ensure_ascii=False))


if __name__ == "__main__":
    main()
