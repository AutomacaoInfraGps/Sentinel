"""Substitui somente as três evidências do modelo da auditoria Linux."""

from __future__ import annotations

import argparse
import copy
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
SLOTS = {"p005_1", "p023_1", "p024_1"}
EXTRA_SLOTS = {"p023_2"}
DEFAULT_DATA = ROOT / "dados" / "execucoes" / "Linux" / "Dados-AuditoriaLinux.json"


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


def resize_drawing(paragraph: ET.Element, path: Path) -> None:
    width, height = png_dimensions(path)
    # Mantém a imagem dentro da área útil da página do documento modelo.
    scale = min(1.0, 5943600 / width / 9525, 7589520 / height / 9525)
    cx, cy = str(round(width * 9525 * scale)), str(round(height * 9525 * scale))
    for extent in paragraph.findall(".//wp:extent", NS) + paragraph.findall(".//a:xfrm/a:ext", NS):
        extent.set("cx", cx)
        extent.set("cy", cy)


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


def canonical(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in normalized if character.isalnum())


def cell_text(cell: ET.Element) -> str:
    return " ".join("".join(item.text or "" for item in cell.findall(".//w:t", NS)).split())


def set_cell_text(cell: ET.Element, value: str) -> None:
    texts = cell.findall(".//w:t", NS)
    if texts:
        texts[0].text = value
        for item in texts[1:]:
            item.text = ""
        return
    paragraph = cell.find("w:p", NS)
    if paragraph is None:
        paragraph = ET.SubElement(cell, f"{{{W}}}p")
    run = ET.SubElement(paragraph, f"{{{W}}}r")
    ET.SubElement(run, f"{{{W}}}t").text = value


def record_value(record: dict[str, str], *names: str) -> str:
    wanted = {canonical(name) for name in names}
    for key, value in record.items():
        if canonical(key) in wanted:
            return value.strip()
    return ""


def default_description(system: str, login: str, role: str) -> str:
    if system == "zabbix":
        if canonical(role) == canonical("Super admin role"):
            return "Usuário usado para administrar o Zabbix"
        return "Usuário genérico da regional usado para autorizar visualização da dashboard específica e integração para envio de alertas"
    if canonical(role) == canonical("Admin"):
        return "Usuário usado para administrar o Grafana"
    return "Usuário com permissão para acessar a dashboard da sua respectiva regional"


def update_user_table(table: ET.Element, records: list[dict[str, str]], system: str) -> int:
    rows = table.findall("w:tr", NS)
    if len(rows) < 2:
        raise ValueError(f"Tabela do {system} sem linhas de modelo")

    existing: dict[str, tuple[ET.Element, str]] = {}
    role_templates: dict[str, ET.Element] = {}
    for row in rows[1:]:
        cells = row.findall("w:tc", NS)
        if len(cells) < 3:
            continue
        login, role, description = (cell_text(cell) for cell in cells[:3])
        existing[canonical(login)] = (row, description)
        role_templates.setdefault(canonical(role), row)

    fallback = rows[1]
    for row in rows[1:]:
        table.remove(row)

    inserted = 0
    for record in records:
        login = record_value(record, "Username", "Login")
        role = record_value(record, "User role", "Role", "Permissão")
        if not login or not role:
            continue
        previous = existing.get(canonical(login))
        template = previous[0] if previous else role_templates.get(canonical(role), fallback)
        description = previous[1] if previous else default_description(system, login, role)
        row = copy.deepcopy(template)
        cells = row.findall("w:tc", NS)
        set_cell_text(cells[0], login)
        set_cell_text(cells[1], role)
        set_cell_text(cells[2], description)
        table.append(row)
        inserted += 1
    return inserted


def render(model: Path, evidence_dir: Path, target: Path, data_path: Path | None = DEFAULT_DATA) -> dict:
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

    table_counts = {"zabbix": 0, "grafana": 0}
    if data_path is not None and data_path.is_file():
        data = json.loads(data_path.read_text(encoding="utf-8-sig"))
        tables = body.findall("w:tbl", NS)
        if len(tables) < 2:
            raise ValueError("O modelo não contém as tabelas de Zabbix e Grafana")
        table_counts["zabbix"] = update_user_table(tables[0], data.get("zabbix", []), "zabbix")
        table_counts["grafana"] = update_user_table(tables[1], data.get("grafana", []), "grafana")
        if not table_counts["zabbix"] or not table_counts["grafana"]:
            raise ValueError("A coleta não contém usuários suficientes para atualizar as tabelas")

    paragraphs = body.findall("w:p", NS)
    found_slots: set[str] = set()
    captured_slots: list[str] = []
    media: dict[str, bytes] = {}
    relation_count = 0
    insertions: list[tuple[ET.Element, ET.Element]] = []

    def bind(paragraph: ET.Element, path: Path, slot: str) -> None:
        nonlocal relation_count
        blips = paragraph.findall(".//a:blip", NS)
        if len(blips) != 1:
            raise ValueError(f"Parágrafo de evidência inesperado em {slot}: {len(blips)} imagens")
        relation_count += 1
        rel_id = f"rIdLinuxAudit{relation_count}"
        media_name = f"auditoria_linux_{slot}.png"
        blips[0].set(f"{{{R}}}embed", rel_id)
        resize_drawing(paragraph, path)
        ET.SubElement(
            relationships,
            f"{{{REL}}}Relationship",
            {"Id": rel_id, "Type": IMAGE_REL, "Target": f"media/{media_name}"},
        )
        media[f"word/media/{media_name}"] = path.read_bytes()
        captured_slots.append(slot)

    for paragraph_index, paragraph in enumerate(paragraphs):
        original_blips = list(paragraph.findall(".//a:blip", NS))
        for number, blip in enumerate(original_blips, 1):
            slot = f"p{paragraph_index:03}_{number}"
            if slot not in SLOTS:
                raise ValueError(f"Imagem inesperada no modelo: {slot}")
            found_slots.add(slot)
            path = evidence_dir / f"{slot}.png"
            if not path.is_file():
                remove_drawing(paragraph, blip)
                continue

            bind(paragraph, path, slot)
            if slot == "p023_1":
                continuation = evidence_dir / "p023_2.png"
                if continuation.is_file():
                    clone = image_only_paragraph(paragraph)
                    bind(clone, continuation, "p023_2")
                    insertions.append((paragraph, clone))

    if found_slots != SLOTS:
        missing = ", ".join(sorted(SLOTS - found_slots))
        raise ValueError(f"O modelo não contém todos os espaços esperados: {missing}")

    for paragraph, addition in insertions:
        body.insert(list(body).index(paragraph) + 1, addition)

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
        output.writestr(
            "word/_rels/document.xml.rels",
            serialize_xml(relationships, relationship_namespaces),
        )
        for name, payload in media.items():
            output.writestr(name, payload)
    temporary.replace(target)

    return {
        "documento": str(target.resolve()),
        "posicoes_preenchidas": len(captured_slots),
        "total_posicoes": len(SLOTS | EXTRA_SLOTS),
        "capturas": captured_slots,
        "linhas_tabelas": table_counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("modelo", type=Path)
    parser.add_argument("evidencias", type=Path)
    parser.add_argument("saida", type=Path)
    parser.add_argument("--dados", type=Path, default=DEFAULT_DATA)
    args = parser.parse_args()
    result = render(args.modelo, args.evidencias, args.saida, args.dados)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
