#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coleta certificados do servidor Acrab e salva em JSON.

Regras:
- Lê credenciais do arquivo de backup `estrutura_regionais.backup_20260522_102235.json`.
- Usa WinRM (Invoke-Command) via PowerShell local para executar comando remoto.
- Salva resultado tratado em `certificate_disk_report_acrab.json`.
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from datetime import datetime


WORKDIR = Path(__file__).resolve().parents[0]
BACKUP_FILE = WORKDIR / "estrutura_regionais.backup_20260522_102235.json"
SECONDARY_FILE = WORKDIR / "estrutura_regionais.json"
OUTPUT_FILE = WORKDIR / "certificate_disk_report_acrab.json"
LOG_DIR = WORKDIR / "logs"
LOG_FILE = LOG_DIR / "error.log"
TARGET_IP = "10.254.13.10"


def log_error(msg: str):
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().isoformat()
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{ts} - {msg}\n")
    except Exception:
        pass


def load_credentials_from_backup(ip: str):
    # Try primary backup first, then secondary full file
    candidates = [BACKUP_FILE, SECONDARY_FILE]
    last_exc = None
    for f in candidates:
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            last_exc = exc
            continue

        regionais = data.get("regionais") if isinstance(data, dict) else None
        if not isinstance(regionais, dict):
            continue

        for chave, reg in regionais.items():
            servidores = (reg or {}).get("servidores") or []
            if not isinstance(servidores, list):
                continue
            for srv in servidores:
                srv_ip = str(srv.get("ip") or srv.get("address") or "").strip()
                if not srv_ip:
                    continue
                if srv_ip == str(ip):
                    usuario = srv.get("usuario") or srv.get("login") or srv.get("user")
                    senha = srv.get("senha") or srv.get("password") or srv.get("pass")
                    if not usuario or not senha:
                        raise RuntimeError("Credenciais encontradas, mas incompletas no backup")
                    nome = srv.get("nome") or srv.get("host") or None
                    return {
                        "username": usuario,
                        "password": senha,
                        "host": nome or ip,
                        "source_file": str(f),
                    }

    if last_exc:
        raise RuntimeError(f"Falha ao ler arquivos de credenciais: {last_exc}")
    raise RuntimeError(f"Nenhum servidor com IP {ip} encontrado nos arquivos {candidates}")


def escape_ps(value: str) -> str:
    return str(value).replace("'", "''")


def run_remote_powershell(host: str, username: str, password: str, script_block: str):
    # Build a PowerShell command that creates PSCredential and runs Invoke-Command
    ps = textwrap.dedent(f"""
        $pw = ConvertTo-SecureString '{escape_ps(password)}' -AsPlainText -Force
        $cred = New-Object System.Management.Automation.PSCredential('{escape_ps(username)}', $pw)
        Invoke-Command -ComputerName {host} -Credential $cred -Authentication Negotiate -ScriptBlock {{ {script_block} }} -ErrorAction Stop | ConvertTo-Json -Depth 4
    """)

    try:
        proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True, timeout=120)
    except Exception as exc:
        raise RuntimeError(f"Falha ao executar PowerShell local: {exc}")

    if proc.returncode != 0:
        # include stderr/stdout for diagnostics
        raise RuntimeError(f"PowerShell error: {proc.stderr.strip() or proc.stdout.strip()}")

    out = proc.stdout.strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        # sometimes PS returns a single object without array; attempt to parse loosely
        try:
            return json.loads(out.replace("\n", ""))
        except Exception as exc:
            raise RuntimeError(f"Falha ao interpretar JSON retornado pelo remoto: {exc}\nRAW:\n{out}")


def normalize_cert_entry(entry: dict) -> dict:
    # Keys may be TitleCase; normalize to required keys
    thumb = entry.get("Thumbprint") or entry.get("thumbprint") or entry.get("Thumbprint ")
    subject = entry.get("Subject") or entry.get("subject")
    issuer = entry.get("Issuer") or entry.get("issuer")
    notafter = entry.get("NotAfter") or entry.get("NotAfter ") or entry.get("NotAfterUtc") or entry.get("notAfter")

    # Convert date-like objects to ISO date string if possible
    if isinstance(notafter, dict) and "DateTime" in notafter:
        notafter = notafter.get("DateTime")

    if hasattr(notafter, "isoformat"):
        notafter = notafter.isoformat()

    # Handle JSON.NET /Date(milliseconds)/ format from PowerShell
    notafter_str = str(notafter).strip() if notafter else None
    if notafter_str and notafter_str.startswith("/Date(") and notafter_str.endswith(")/"):
        try:
            ms_str = notafter_str[6:-2]  # Extract milliseconds from "/Date(1752191999000)/"
            ms = int(ms_str)
            from datetime import datetime
            dt = datetime.utcfromtimestamp(ms / 1000.0)
            notafter_str = dt.isoformat() + "Z"
        except Exception:
            pass  # Fall back to original string if conversion fails

    result = {
        "thumbprint": str(thumb).strip() if thumb else None,
        "subject": str(subject).strip() if subject else None,
        "issuer": str(issuer).strip() if issuer else None,
        "notAfter": notafter_str,
    }
    return result


def main():
    try:
        creds = load_credentials_from_backup(TARGET_IP)
    except Exception as exc:
        log_error(f"Erro ao carregar credenciais: {exc}")
        print(f"Erro ao carregar credenciais: {exc}")
        sys.exit(1)

    username = creds["username"]
    password = creds["password"]
    host = creds.get("host") or TARGET_IP

    # Prefer hostname for Negotiate/Kerberos if provided
    if str(host).lower() == str(TARGET_IP):
        invoke_host = TARGET_IP
    else:
        invoke_host = host

    ps_script_block = r"Get-ChildItem Cert:\LocalMachine\My | Where-Object { $_.Subject -like '*galaxia*' } | Select-Object Thumbprint, Subject, Issuer, NotAfter"

    try:
        remote_json = run_remote_powershell(invoke_host, username, password, ps_script_block)
    except Exception as exc:
        log_error(f"Erro ao executar remoto: {exc}")
        print(f"Erro ao executar remoto: {exc}")
        sys.exit(2)

    if remote_json is None:
        log_error("Comando remoto retornou sem dados")
        print("Nenhum certificado encontrado ou saída vazia")
        sys.exit(3)

    # Normalize into list
    if isinstance(remote_json, dict):
        certs = [remote_json]
    elif isinstance(remote_json, list):
        certs = remote_json
    else:
        log_error(f"Formato inesperado do retorno remoto: {type(remote_json)}")
        print("Formato inesperado do retorno remoto")
        sys.exit(4)

    processed = []
    for item in certs:
        if not isinstance(item, dict):
            continue
        processed.append(normalize_cert_entry(item))

    # Save to output file
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(processed, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        log_error(f"Erro ao gravar arquivo JSON: {exc}")
        raise

    if not OUTPUT_FILE.exists():
        raise RuntimeError("Arquivo JSON não foi criado")

    print(f"Relatório salvo em: {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
