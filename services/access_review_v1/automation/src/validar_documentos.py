"""Valida a estrutura Open XML dos DOCX produzidos por um lote."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree as ET

REQUIRED={"[Content_Types].xml","word/document.xml","word/_rels/document.xml.rels"}

def validate(path:Path)->dict:
    item={"arquivo":str(path.resolve()),"valido":False,"erro":None}
    try:
        if not path.is_file() or path.stat().st_size<10_000: raise ValueError("arquivo ausente ou pequeno demais")
        with ZipFile(path) as package:
            broken=package.testzip()
            if broken: raise ValueError(f"entrada ZIP corrompida: {broken}")
            missing=REQUIRED-set(package.namelist())
            if missing: raise ValueError("partes obrigatórias ausentes: "+", ".join(sorted(missing)))
            ET.fromstring(package.read("[Content_Types].xml"))
            document=ET.fromstring(package.read("word/document.xml"))
            ns={"w":"http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            if document.find(".//w:body",ns) is None: raise ValueError("document.xml sem corpo")
        item["valido"]=True
    except (BadZipFile,ET.ParseError,ValueError,OSError) as error: item["erro"]=str(error)
    return item

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("directory",type=Path,nargs="?"); ap.add_argument("--file",type=Path); ap.add_argument("--expected",type=int,default=1); ap.add_argument("--output",type=Path); args=ap.parse_args()
    if bool(args.directory) == bool(args.file):
        ap.error("informe um diretorio ou --file")
    docs=[args.file] if args.file else sorted(args.directory.glob("*.docx"))
    base=args.file.parent if args.file else args.directory
    result={"diretorio":str(base.resolve()),"esperados":args.expected,"encontrados":len(docs),"documentos":[validate(p) for p in docs]}
    result["valido"]=len(docs)==args.expected and all(x["valido"] for x in result["documentos"])
    payload=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output: args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(payload,encoding="utf-8")
    print(payload)
    raise SystemExit(0 if result["valido"] else 1)
if __name__=="__main__": main()
