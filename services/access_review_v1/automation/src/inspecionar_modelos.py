"""Lista seções, textos e capturas incorporadas em DOCX de referência."""

from __future__ import annotations

import json
import sys
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

N = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def inspect(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
        relationships = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        targets = {x.attrib["Id"]: x.attrib["Target"] for x in relationships}
        paragraphs = []
        for index, node in enumerate(root.findall("./w:body/w:p", N)):
            style_node = node.find("w:pPr/w:pStyle", N)
            style = style_node.attrib.get(f"{{{N['w']}}}val") if style_node is not None else ""
            text = "".join(x.text or "" for x in node.findall(".//w:t", N)).strip()
            images = []
            for image in node.findall(".//a:blip", N):
                rel_id = image.attrib.get(f"{{{N['r']}}}embed")
                if rel_id:
                    images.append(targets.get(rel_id, rel_id))
            if text or images:
                paragraphs.append({"indice": index, "estilo": style, "texto": text, "imagens": images})
        media = [name for name in archive.namelist() if name.startswith("word/media/")]
    return {
        "arquivo": path.name,
        "paragrafos": paragraphs,
        "imagens_embutidas": len(media),
        "referencias_imagens": sum(len(x["imagens"]) for x in paragraphs),
        "estilos": dict(Counter(x["estilo"] for x in paragraphs)),
    }


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Uso: python tools/inspecionar_modelos.py arquivo.docx [...]")
    for source in sys.argv[1:]:
        info = inspect(Path(source))
        print(f"\n{info['arquivo']}: {info['imagens_embutidas']} mídias, {info['referencias_imagens']} referências")
        for entry in info["paragrafos"]:
            text = entry["texto"]
            if entry["estilo"].startswith("Ttulo") or text.startswith(("OU ", "Grupo GGS_")):
                print(f"[{entry['indice']:03}] {entry['estilo']}: {text[:105]}")
        if len(sys.argv) == 2:
            target = Path("dados/execucoes/Modelo-ServidoresWindows-manifesto.json")
            target.parent.mkdir(exist_ok=True)
            target.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Manifesto salvo em {target}")
            print("\nEstrutura inicial:")
            for entry in info["paragrafos"]:
                if entry["indice"] < 78 or 498 <= entry["indice"] <= 550:
                    print(f"[{entry['indice']:03}] img={len(entry['imagens'])} {entry['texto'][:110]}")
            selections = {7, 8, 12, 25, 35, 40, 42, 46, 48, 51, 56, 58, 64, 67, 70, 73, 75, 500, 502, 503, 505, 508, 531, 537}
            image_dir = Path("dados/execucoes/Modelo-Imagens")
            image_dir.mkdir(exist_ok=True)
            with zipfile.ZipFile(source) as archive:
                for entry in info["paragrafos"]:
                    if entry["indice"] in selections:
                        for number, image in enumerate(entry["imagens"], 1):
                            target = image_dir / f"p{entry['indice']:03}-{number}.png"
                            target.write_bytes(archive.read("word/" + image))
            print(f"Imagens de amostra salvas em {image_dir}")


if __name__ == "__main__":
    main()
