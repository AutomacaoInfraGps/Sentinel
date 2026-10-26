"""Atualiza as evidências do DOCX modelo sem reconstruir seu conteúdo editorial."""

from __future__ import annotations

import copy
import argparse
import io
import json
import struct
import unicodedata
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
CODE_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__import__("os").environ["SENTINEL_ACCESS_REVIEW_HOME"])
# Espaços que separavam as cinco imagens antigas da ACL. Com apenas duas telas,
# um único parágrafo vazio após a sequência é suficiente.
REDUNDANT_EMPTY_PARAGRAPHS = {31, 32}


def canonical_text(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(char)
    )


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
    """Preserva os prefixos citados por mc:Ignorable para o Word não reparar o DOCX."""
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    ignorable = root.attrib.get(f"{{{MC}}}Ignorable", "").split()
    declaration_end = payload.find(b"?>")
    root_start = payload.find(b"<", declaration_end + 2)
    root_end = payload.find(b">", root_start)
    start_tag = payload[root_start:root_end]
    additions = []
    for prefix in ignorable:
        marker = f"xmlns:{prefix}=".encode("ascii")
        if marker not in start_tag:
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


def resize_drawing(node: ET.Element, path: Path) -> None:
    width, height = png_dimensions(path)
    scale = min(1.0, 5943600 / width / 9525, 7589520 / height / 9525)
    cx, cy = str(round(width * 9525 * scale)), str(round(height * 9525 * scale))
    for extent in node.findall(".//wp:extent", NS) + node.findall(".//a:xfrm/a:ext", NS):
        extent.set("cx", cx)
        extent.set("cy", cy)


def center_paragraph(paragraph: ET.Element) -> None:
    """Mantém todas as evidências com o mesmo alinhamento visual."""
    properties = paragraph.find("w:pPr", NS)
    if properties is None:
        properties = ET.Element(f"{{{W}}}pPr")
        paragraph.insert(0, properties)
    alignment = properties.find("w:jc", NS)
    if alignment is None:
        alignment = ET.SubElement(properties, f"{{{W}}}jc")
    alignment.set(f"{{{W}}}val", "center")


def remove_trailing_page_breaks(body: ET.Element) -> None:
    """Evita uma página vazia quando as seções posteriores são retiradas."""
    children = list(body)
    section_properties = next((item for item in reversed(children) if item.tag == f"{{{W}}}sectPr"), None)
    candidates = children[:children.index(section_properties)] if section_properties is not None else children
    for paragraph in reversed(candidates):
        text = "".join(item.text or "" for item in paragraph.findall(".//w:t", NS)).strip()
        drawings = paragraph.findall(".//w:drawing", NS)
        page_breaks = [
            item for item in paragraph.findall(".//w:br", NS)
            if item.attrib.get(f"{{{W}}}type") == "page"
        ]
        if text or drawings:
            break
        if page_breaks and paragraph in list(body):
            body.remove(paragraph)


def remove_drawing(paragraph: ET.Element, blip: ET.Element) -> None:
    for run in paragraph.findall(".//w:r", NS):
        for drawing in list(run.findall("w:drawing", NS)):
            if blip in drawing.findall(".//a:blip", NS):
                run.remove(drawing)
        if not list(run) and run in list(paragraph):
            paragraph.remove(run)


def image_only_paragraph(source: ET.Element) -> ET.Element:
    paragraph = copy.deepcopy(source)
    for run in list(paragraph.findall("w:r", NS)):
        if not run.findall(".//w:drawing", NS):
            paragraph.remove(run)
    for text in paragraph.findall(".//w:t", NS):
        text.text = ""
    return paragraph


def replace_paragraph_text(paragraph: ET.Element, value: str) -> None:
    """Substitui o texto editorial preservando o estilo do primeiro trecho."""
    nodes = paragraph.findall(".//w:t", NS)
    if not nodes:
        return
    nodes[0].text = value
    for node in nodes[1:]:
        node.text = ""


def render(
    model: Path,
    inventory_path: Path,
    target: Path,
    included_sections: set[str] | None = None,
    included_slots: set[str] | None = None,
    include_preamble: bool = True,
) -> dict:
    inventory = json.loads(inventory_path.read_text(encoding="utf-8-sig"))
    known_slots = {item["slot"] for item in inventory["slots"]}
    slot_records = {item["slot"]: item for item in inventory["slots"]}
    evidence_dir = ROOT / "dados" / "evidencias" / "ServidoresWindows"

    with zipfile.ZipFile(model) as source:
        document_xml = source.read("word/document.xml")
        relationships_xml = source.read("word/_rels/document.xml.rels")
        document_namespaces = namespace_map(document_xml)
        relationship_namespaces = namespace_map(relationships_xml)
        document = ET.fromstring(document_xml)
        relationships = ET.fromstring(relationships_xml)
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
    paragraphs = body.findall("w:p", NS)
    media: dict[str, bytes] = {}
    captured_slots: list[str] = []
    image_count = 0
    relation_count = 0

    def bind(paragraph: ET.Element, path: Path, slot: str) -> None:
        nonlocal image_count, relation_count
        blips = paragraph.findall(".//a:blip", NS)
        if len(blips) != 1:
            raise ValueError(f"Parágrafo de evidência inesperado em {slot}: {len(blips)} imagens")
        relation_count += 1
        rel_id = f"rIdAudit{relation_count}"
        media_name = f"audit_{slot}.png"
        blips[0].set(f"{{{R}}}embed", rel_id)
        center_paragraph(paragraph)
        resize_drawing(paragraph, path)
        ET.SubElement(relationships, f"{{{REL}}}Relationship", {
            "Id": rel_id,
            "Type": IMAGE_REL,
            "Target": f"media/{media_name}",
        })
        media[f"word/media/{media_name}"] = path.read_bytes()
        image_count += 1

    insertions: list[tuple[ET.Element, list[ET.Element]]] = []
    removals: list[ET.Element] = []
    current_section: str | None = None
    for paragraph_index, paragraph in enumerate(paragraphs):
        original_blips = list(paragraph.findall(".//a:blip", NS))
        text = "".join(item.text or "" for item in paragraph.findall(".//w:t", NS)).strip()
        normalized_text = canonical_text(text)
        if normalized_text.startswith("servidor shaula") and "ad ds" in normalized_text:
            replace_paragraph_text(paragraph, "Servidor Rigel – Server Manager.")
            text = "Servidor Rigel – Server Manager."
        elif normalized_text.startswith("o servidor shaula possui o servico active directory ativo"):
            replace_paragraph_text(
                paragraph,
                "Rigel tem o módulo AD do Galaxia. O Server Manager do Rigel apresenta o painel de administração e as informações locais do servidor.",
            )
            text = "Rigel tem o módulo AD do Galaxia. O Server Manager do Rigel apresenta o painel de administração e as informações locais do servidor."
        style_node = paragraph.find("w:pPr/w:pStyle", NS)
        style = style_node.attrib.get(f"{{{W}}}val", "") if style_node is not None else ""
        if style == "Ttulo2" and text.startswith("OU "):
            current_section = text.rstrip(".")
        if included_sections is not None and not include_preamble and current_section is None:
            removals.append(paragraph)
            continue
        if current_section is not None and included_sections is not None and current_section not in included_sections:
            removals.append(paragraph)
            continue
        for number, blip in enumerate(original_blips, 1):
            slot = f"p{paragraph_index:03}_{number}"
            path = evidence_dir / f"{slot}.png"
            if slot not in known_slots or (included_slots is not None and slot not in included_slots) or not path.is_file():
                remove_drawing(paragraph, blip)
                continue
            bind(paragraph, path, slot)
            captured_slots.append(slot)
            prefix = slot.removesuffix("_1")
            description = canonical_text(slot_records[slot]["descricao"])
            extras = [] if "grupo de bloqueio" in description else sorted(
                (item for item in evidence_dir.glob(f"{prefix}_*.png") if item.stem not in known_slots),
                key=lambda item: int(item.stem.rsplit("_", 1)[-1]),
            )
            additions = []
            for extra in extras:
                clone = image_only_paragraph(paragraph)
                bind(clone, extra, extra.stem)
                additions.append(clone)
            if additions:
                insertions.append((paragraph, additions))
        if paragraph_index in REDUNDANT_EMPTY_PARAGRAPHS and not text and not original_blips:
            removals.append(paragraph)
            continue
        if original_blips and not paragraph.findall(".//a:blip", NS) and not text:
            removals.append(paragraph)

    for paragraph, additions in insertions:
        position = list(body).index(paragraph) + 1
        for addition in additions:
            body.insert(position, addition)
            position += 1
    for paragraph in removals:
        if paragraph in list(body):
            body.remove(paragraph)
    remove_trailing_page_breaks(body)

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
    total_slots = len(included_slots) if included_slots is not None else len(known_slots)
    return {"captured_slots": len(captured_slots), "images": image_count, "total_slots": total_slots}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("modelo", type=Path)
    parser.add_argument("inventario", type=Path)
    parser.add_argument("saida", type=Path)
    parser.add_argument("--sections-file", type=Path)
    args = parser.parse_args()
    included = None
    included_slots = None
    include_preamble = True
    if args.sections_file:
        plan = json.loads(args.sections_file.read_text(encoding="utf-8-sig"))
        values = plan.get("secoes", plan) if isinstance(plan, dict) else plan
        included = set(values)
        if isinstance(plan, dict) and "slots" in plan:
            included_slots = set(plan["slots"])
        if isinstance(plan, dict):
            include_preamble = bool(plan.get("incluir_bloco_inicial", True))
    result = render(args.modelo, args.inventario, args.saida, included, included_slots, include_preamble)
    print(
        f"Documento baseado no modelo: {args.saida} | "
        f"posições preenchidas: {result['captured_slots']}/{result['total_slots']}; imagens: {result['images']}"
    )


if __name__ == "__main__":
    main()
