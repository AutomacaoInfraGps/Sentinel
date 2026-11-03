"""Substitui as duas evidências do modelo da auditoria ADManager."""

from __future__ import annotations

import argparse
import io
import json
import struct
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
IMAGE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
NS = {"w": W, "a": A, "r": R, "wp": WP, "rel": REL}
SLOTS = {"p003_1", "p005_1"}


def namespace_map(payload: bytes) -> dict[str, str]:
    namespaces: dict[str, str] = {}
    for _, item in ET.iterparse(io.BytesIO(payload), events=("start-ns",)):
        prefix, uri = item
        namespaces[prefix or ""] = uri
    for prefix, uri in namespaces.items():
        if prefix != "xml" and not prefix.startswith("ns"):
            ET.register_namespace(prefix, uri)
    return namespaces


def serialize_xml(root: ET.Element, namespaces: dict[str, str]) -> bytes:
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    ignorable = root.attrib.get(f"{{{MC}}}Ignorable", "").split()
    declaration_end = payload.find(b"?>")
    root_start = payload.find(b"<", declaration_end + 2)
    root_end = payload.find(b">", root_start)
    start_tag = payload[root_start:root_end]
    additions = []
    for prefix in ignorable:
        if f"xmlns:{prefix}=".encode("ascii") not in start_tag:
            uri = namespaces.get(prefix)
            if not uri:
                raise ValueError(f"Namespace ausente para mc:Ignorable: {prefix}")
            additions.append(f' xmlns:{prefix}="{uri}"'.encode("utf-8"))
    if additions:
        payload = payload[:root_end] + b"".join(additions) + payload[root_end:]
    return payload


def png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError(f"PNG inválido: {path}")
    return struct.unpack(">II", header[16:24])


def resize_drawing(paragraph: ET.Element, path: Path) -> None:
    width, height = png_dimensions(path)
    scale = min(1.0, 5943600 / width / 9525, 7589520 / height / 9525)
    cx, cy = str(round(width * 9525 * scale)), str(round(height * 9525 * scale))
    for extent in paragraph.findall(".//wp:extent", NS) + paragraph.findall(".//a:xfrm/a:ext", NS):
        extent.set("cx", cx)
        extent.set("cy", cy)


def render(model: Path, evidence_dir: Path, target: Path) -> dict:
    with zipfile.ZipFile(model) as source:
        document_payload = source.read("word/document.xml")
        relationships_payload = source.read("word/_rels/document.xml.rels")
        document_namespaces = namespace_map(document_payload)
        relationship_namespaces = namespace_map(relationships_payload)
        document = ET.fromstring(document_payload)
        relationships = ET.fromstring(relationships_payload)
        source_entries = {name: source.read(name) for name in source.namelist()}

    old_image_targets = {
        "word/" + item.attrib["Target"]
        for item in relationships
        if item.attrib.get("Type") == IMAGE_REL
    }
    for item in list(relationships):
        if item.attrib.get("Type") == IMAGE_REL:
            relationships.remove(item)

    body = document.find("w:body", NS)
    if body is None:
        raise ValueError("Documento sem corpo")
    found: set[str] = set()
    captured: list[str] = []
    media: dict[str, bytes] = {}
    relation_count = 0
    for paragraph_index, paragraph in enumerate(body.findall("w:p", NS)):
        for number, blip in enumerate(paragraph.findall(".//a:blip", NS), 1):
            slot = f"p{paragraph_index:03}_{number}"
            if slot not in SLOTS:
                raise ValueError(f"Imagem inesperada no modelo: {slot}")
            found.add(slot)
            path = evidence_dir / f"{slot}.png"
            if not path.is_file():
                raise ValueError(f"Evidência ausente: {path}")
            relation_count += 1
            rel_id = f"rIdADManagerAudit{relation_count}"
            media_name = f"auditoria_admanager_{slot}.png"
            blip.set(f"{{{R}}}embed", rel_id)
            resize_drawing(paragraph, path)
            ET.SubElement(
                relationships,
                f"{{{REL}}}Relationship",
                {"Id": rel_id, "Type": IMAGE_REL, "Target": f"media/{media_name}"},
            )
            media[f"word/media/{media_name}"] = path.read_bytes()
            captured.append(slot)

    if found != SLOTS:
        raise ValueError("O modelo não contém as duas posições de evidência esperadas")
    for doc_id, item in enumerate(document.findall(".//wp:docPr", NS), 1):
        item.set("id", str(doc_id))

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".docx.tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as output:
        for name, payload in source_entries.items():
            if name in {"word/document.xml", "word/_rels/document.xml.rels"} or name in old_image_targets:
                continue
            output.writestr(name, payload)
        output.writestr("word/document.xml", serialize_xml(document, document_namespaces))
        output.writestr("word/_rels/document.xml.rels", serialize_xml(relationships, relationship_namespaces))
        for name, payload in media.items():
            output.writestr(name, payload)
    temporary.replace(target)
    return {"documento": str(target.resolve()), "posicoes_preenchidas": len(captured), "capturas": captured}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("modelo", type=Path)
    parser.add_argument("evidencias", type=Path)
    parser.add_argument("saida", type=Path)
    args = parser.parse_args()
    print(json.dumps(render(args.modelo, args.evidencias, args.saida), ensure_ascii=False))


if __name__ == "__main__":
    main()
