"""Valida as evidências e a estrutura do DOCX de Servidores Windows."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import unicodedata
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET


CODE_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__import__("os").environ["SENTINEL_ACCESS_REVIEW_HOME"])
INVENTORY = ROOT / "dados" / "execucoes" / "Inventario-Evidencias-ServidoresWindows.json"
EVIDENCE = ROOT / "dados" / "evidencias" / "ServidoresWindows"
DEFAULT_DOCX = ROOT / "dados" / "execucoes" / "ServidoresWindows" / "Auditoria Galaxia Servidores Windows - Teste Completo.docx"

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
}


def canonical(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in value if not unicodedata.combining(ch)).casefold()


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def png_dimensions(payload: bytes) -> tuple[int, int]:
    if len(payload) < 24 or payload[:8] != b"\x89PNG\r\n\x1a\n" or payload[12:16] != b"IHDR":
        raise ValueError("assinatura PNG inválida")
    return struct.unpack(">II", payload[16:24])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docx", type=Path, default=DEFAULT_DOCX)
    parser.add_argument("--sections-file", type=Path)
    args = parser.parse_args()
    errors: list[str] = []
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    slots = inventory["slots"]
    if args.sections_file:
        plan = json.loads(args.sections_file.read_text(encoding="utf-8-sig"))
        selected = set(plan["slots"])
        slots = [item for item in slots if item["slot"] in selected]
    local = list(slots)
    pending = [item["slot"] for item in local if not (ROOT / item["arquivo_esperado"]).is_file()]

    evidence_payloads: dict[str, bytes] = {}
    for item in local:
        path = ROOT / item["arquivo_esperado"]
        if not path.is_file():
            errors.append(f"evidência ausente: {item['slot']}")
            continue
        payload = path.read_bytes()
        try:
            width, height = png_dimensions(payload)
            if width < 800 or height < 500:
                errors.append(f"imagem pequena: {item['slot']} ({width}x{height})")
        except ValueError as exc:
            errors.append(f"{item['slot']}: {exc}")
        evidence_payloads[item["slot"]] = payload

    obsolete_present = [slot for slot in inventory.get("slots_omitidos", []) if (EVIDENCE / f"{slot}.png").exists()]
    if obsolete_present:
        errors.append("slots obsoletos ativos: " + ", ".join(obsolete_present))

    block_slots = [
        item["slot"]
        for item in slots
        if "grupo de bloqueio" in canonical(item.get("descricao", ""))
    ]
    block_extras: list[str] = []
    for slot in block_slots:
        stem = slot.rsplit("_", 1)[0]
        files = sorted(EVIDENCE.glob(f"{stem}_*.png"))
        if [path.name for path in files] != [f"{slot}.png"]:
            block_extras.extend(path.name for path in files if path.name != f"{slot}.png")
    if block_extras:
        errors.append("continuações indevidas de GGS_Bloqueio: " + ", ".join(block_extras))

    with zipfile.ZipFile(args.docx) as archive:
        corrupt = archive.testzip()
        if corrupt:
            errors.append(f"entrada ZIP corrompida: {corrupt}")
        names = archive.namelist()
        if len(names) != len(set(names)):
            errors.append("entradas duplicadas no ZIP")
        xml_names = [name for name in names if name.endswith((".xml", ".rels"))]
        for name in xml_names:
            try:
                ET.fromstring(archive.read(name))
            except ET.ParseError as exc:
                errors.append(f"XML inválido {name}: {exc}")

        document_payload = archive.read("word/document.xml")
        document = ET.fromstring(document_payload)
        relationships = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        rel_map = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in relationships.findall("pr:Relationship", NS)
        }
        embeds = [node.attrib[f"{{{NS['r']}}}embed"] for node in document.findall(".//a:blip", NS)]
        for rel_id in embeds:
            target = rel_map.get(rel_id)
            if not target:
                errors.append(f"relação de imagem ausente: {rel_id}")
                continue
            member = "word/" + target.lstrip("/")
            if member not in names:
                errors.append(f"mídia ausente para {rel_id}: {member}")

        for paragraph in document.findall(".//w:body/w:p", NS):
            paragraph_embeds = [node.attrib[f"{{{NS['r']}}}embed"] for node in paragraph.findall(".//a:blip", NS)]
            audit_targets = [rel_map.get(rel_id, "") for rel_id in paragraph_embeds]
            if any(target.startswith("media/audit_") for target in audit_targets):
                alignment = paragraph.find("w:pPr/w:jc", NS)
                if alignment is None or alignment.attrib.get(f"{{{NS['w']}}}val") != "center":
                    errors.append("evidência sem alinhamento centralizado: " + ", ".join(audit_targets))

        deny_slots = [
            item for item in slots
            if "membros diretos do grupo de bloqueio" in canonical(item.get("descricao", ""))
        ]
        member_text = "membros ativos: definidos para manter o controle de seguranca"
        member_paragraphs = [
            paragraph for paragraph in document.findall(".//w:body/w:p", NS)
            if member_text in canonical("".join(item.text or "" for item in paragraph.findall(".//w:t", NS)))
        ]
        if len(member_paragraphs) != len(deny_slots):
            errors.append(
                "quantidade incorreta do texto de Membros Ativos: "
                f"{len(member_paragraphs)} no documento para {len(deny_slots)} evidências Deny"
            )
        for paragraph in member_paragraphs:
            if paragraph.find("w:pPr/w:numPr", NS) is None:
                errors.append("texto de Membros Ativos sem o marcador do modelo")
            first_text_run = next(
                (
                    run for run in paragraph.findall("w:r", NS)
                    if "".join(item.text or "" for item in run.findall(".//w:t", NS)).strip()
                ),
                None,
            )
            style = first_text_run.find("w:rPr/w:rStyle", NS) if first_text_run is not None else None
            if style is None or style.attrib.get(f"{{{NS['w']}}}val") != "Forte":
                errors.append("rótulo Membros Ativos sem o destaque do modelo")

        document_text = canonical(" ".join(text.strip() for text in document.itertext() if text.strip()))
        if {"p007_1", "p008_1"}.issubset({item["slot"] for item in slots}):
            if "servidor rigel" not in document_text or "server manager do rigel" not in document_text:
                errors.append("identificação do Rigel ausente no bloco do Server Manager")
            if "rigel tem o modulo ad do galaxia" not in document_text:
                errors.append("informação do módulo AD do Galaxia ausente no bloco do Rigel")

        body = document.find("w:body", NS)
        if body is not None:
            body_items = [item for item in list(body) if item.tag != f"{{{NS['w']}}}sectPr"]
            if body_items:
                trailing_breaks = [
                    item for item in body_items[-1].findall(".//w:br", NS)
                    if item.attrib.get(f"{{{NS['w']}}}type") == "page"
                ]
                if trailing_breaks:
                    errors.append("quebra de página vazia ao final do documento")

        doc_pr_ids = [node.attrib.get("id") for node in document.findall(".//wp:docPr", NS)]
        if len(doc_pr_ids) != len(set(doc_pr_ids)):
            errors.append("IDs wp:docPr duplicados")

        namespace_prefixes = {prefix for _event, (prefix, _uri) in ET.iterparse(BytesIO(document_payload), events=("start-ns",))}
        ignorable = document.attrib.get(f"{{{NS['mc']}}}Ignorable", "").split()
        missing_prefixes = sorted(set(ignorable) - namespace_prefixes)
        if missing_prefixes:
            errors.append("prefixos de mc:Ignorable sem declaração: " + ", ".join(missing_prefixes))

        for slot, payload in evidence_payloads.items():
            member = f"word/media/audit_{slot}.png"
            if member not in names:
                errors.append(f"mídia do slot ausente no DOCX: {slot}")
            elif sha256(archive.read(member)) != sha256(payload):
                errors.append(f"mídia do DOCX difere da evidência: {slot}")

        omitted_media = [
            slot for slot in inventory.get("slots_omitidos", [])
            if f"word/media/audit_{slot}.png" in names
        ]
        if omitted_media:
            errors.append("slots obsoletos incorporados no DOCX: " + ", ".join(omitted_media))

        media_count = sum(name.startswith("word/media/") for name in names)

    summary = {
        "slots_inventario": len(slots),
        "slots_locais": len(local),
        "pendentes": pending,
        "grupos_bloqueio": len(block_slots),
        "midias_docx": media_count,
        "erros": errors,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
