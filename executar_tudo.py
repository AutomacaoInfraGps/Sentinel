# --- GPS Amigo: imports e preparação (topo do arquivo) ---
import sys
from pathlib import Path
# garante que importações peguem C:\Automacao primeiro
sys.path.insert(0, str(Path(__file__).parent.resolve()))
from web_config import gerenciador_fortigate
from gps_print import ensure_gps_placeholder, gerar_print_gps_amigo
from config import GPS_HTML, GPS_CONFIG, APPGATE_HTML, APPGATE_IMG, APPGATE_CONFIG

import subprocess
from pathlib import Path
import webbrowser
import os
import re
import unicodedata
from datetime import datetime
import sys
sys.path.insert(0, str(Path(__file__).parent.resolve()))
import json, html

AUTO_NO_BROWSER = "--no-browser" in sys.argv or os.environ.get("AUTOMACAO_NO_BROWSER", "").strip().lower() in {"1", "true", "yes", "on"}
from config import REPLICACAO_HTML, REPLICACAO_JSON
try:
    from config import REPLICACAO_HTML_FRAGMENT
except Exception:
    REPLICACAO_HTML_FRAGMENT = None

# --- GPS: helpers de renderização (substitua sua função atual por estas duas) ---
import re, base64
from datetime import datetime

def _montar_gps_html():
    """Retorna o HTML a ser exibido no dashboard (preferindo <body> do print_temp;
    se não houver, embute o PNG em base64; se nada, mostra placeholder com link)."""
    try:
        # 1) Tenta usar o HTML gerado (com a imagem já embedada)
        if GPS_HTML.exists():
            txt = GPS_HTML.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"<body[^>]*>(.*?)</body>", txt, flags=re.IGNORECASE | re.DOTALL)
            body = (m.group(1) if m else txt).strip()
            # Se já tem imagem embedada ou <img>, usa direto
            if "data:image/png" in body or "<img" in body:
                updated = datetime.fromtimestamp(GPS_HTML.stat().st_mtime).strftime("%d/%m/%Y %H:%M:%S")
                return body + f'<div class="small" style="color:#666;margin-top:6px">Atualizado: {updated}</div>'
        # 2) Se não, embute o PNG
        png_path = GPS_HTML.with_name("gps_amigo.png")
        if png_path.exists() and png_path.stat().st_size > 10_000:  # >10KB evita falso-positivo
            b64 = base64.b64encode(png_path.read_bytes()).decode("ascii")
            ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return (
                f'<img alt="GPS Amigo" '
                f'style="max-width:100%;height:auto;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,.08)" '
                f'src="data:image/png;base64,{b64}">'
                f'<div class="small" style="color:#666;margin-top:6px">Atualizado: {ts}</div>'
            )
    except Exception as e:
        # não interrompe o fluxo do dashboard
        print("[GPS] Falha montando HTML:", e)

    # 3) Último recurso: placeholder enxuto
    url = GPS_CONFIG.get("url", "https://gpsamigo.com.br/login.php")
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        f'<div class="note" style="color:#666">Prévia indisponível no momento. ({ts})</div>'
        f'<p><a href="{url}" target="_blank">Abrir GPS Amigo</a></p>'
    )

def render_bloco_gps():
    """Card do GPS para ser usado (se você ainda quiser exibir em algum lugar)."""
    return f"""
    <section class="card">
      <h2>Print GPS Amigo</h2>
      <div class="card-body">
        {_montar_gps_html()}
      </div>
    </section>
    """


def _month_abbr_pt_local(month: int) -> str:
    months = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    return months[month - 1]


def _montar_print_rede_html():
    """Monta o HTML com os 3 prints do portal de rede gerados no dia atual."""
    try:
        from config import SATURNO_OUTPUT_BASE

        now = datetime.now()
        out_dir = SATURNO_OUTPUT_BASE / f"{now.year}" / _month_abbr_pt_local(now.month) / f"{now.day:02d}"
        images = [
            ("WI-FI", out_dir / "saturno_wifi.png"),
            ("DIRETORIA", out_dir / "saturno_diretoria.png"),
            ("APROVACAO WI-FI", out_dir / "saturno_wifi_aprovacao.png"),
        ]

        cards = []
        for title, path in images:
            if not path.exists() or path.stat().st_size == 0:
                cards.append(
                    f"""
                    <div style="margin-bottom: 24px;">
                        <h3 style="font-size: 1.1rem; font-weight: 700; margin-bottom: 10px;">{title}</h3>
                        <div class='error'>Print não encontrado: {path}</div>
                    </div>
                    """
                )
                continue

            b64 = base64.b64encode(path.read_bytes()).decode("ascii")
            updated = datetime.fromtimestamp(path.stat().st_mtime).strftime("%d/%m/%Y %H:%M:%S")
            cards.append(
                f"""
                <div style="margin-bottom: 28px;">
                    <h3 style="font-size: 1.1rem; font-weight: 700; margin-bottom: 10px;">{title}</h3>
                    <img alt="{title}" style="max-width:100%;height:auto;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,.08)" src="data:image/png;base64,{b64}">
                    <div class="small" style="color:#666;margin-top:6px">Atualizado: {updated}</div>
                </div>
                """
            )

        return "".join(cards)
    except Exception as e:
        print("[PRINT-REDE] Falha montando HTML:", e)
        return f"<div class='error'>Falha ao montar Print Rede: {e}</div>"


def _montar_appgate_html():
    try:
        if APPGATE_IMG.exists() and APPGATE_IMG.stat().st_size > 10_000:
            b64 = base64.b64encode(APPGATE_IMG.read_bytes()).decode("ascii")
            updated = datetime.fromtimestamp(APPGATE_IMG.stat().st_mtime).strftime("%d/%m/%Y %H:%M:%S")
            return (
                f'<img alt="Firewall Rio de Janeiro" '
                f'style="max-width:100%;height:auto;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,.08)" '
                f'src="data:image/png;base64,{b64}">'
                f'<div class="small" style="color:#666;margin-top:6px">Atualizado: {updated}</div>'
            )

        if APPGATE_HTML.exists():
            txt = APPGATE_HTML.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"<body[^>]*>(.*?)</body>", txt, flags=re.IGNORECASE | re.DOTALL)
            body = (m.group(1) if m else txt).strip()
            if "data:image/png" in body or "<img" in body:
                updated = datetime.fromtimestamp(APPGATE_HTML.stat().st_mtime).strftime("%d/%m/%Y %H:%M:%S")
                return body + f'<div class="small" style="color:#666;margin-top:6px">Atualizado: {updated}</div>'
    except Exception as e:
        print("[APPGATE] Falha montando HTML:", e)

    url = APPGATE_CONFIG.get("url", "https://firewall.example.local/ng/system/dashboard/1")
    ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    return (
        f'<div class="note" style="color:#666">Prévia indisponível no momento. ({ts})</div>'
        f'<p><a href="{url}" target="_blank">Abrir Firewall Rio de Janeiro</a></p>'
    )


def render_replicacao_card():
    """
    Exibe a replicação usando 1) fragmento, 2) HTML completo, ou 3) JSON
    (nesta ordem). Assim evita duplicidade.
    """
    # 1) Fragmento (sem <html>), se existir
    if REPLICACAO_HTML_FRAGMENT and Path(REPLICACAO_HTML_FRAGMENT).exists():
        frag = Path(REPLICACAO_HTML_FRAGMENT).read_text(encoding="utf-8")
        return f'<section class="card"><h2>Replicação AD</h2><div class="card-body">{frag}</div></section>'

    # 2) HTML completo (gerado pelo PS1)
    if Path(REPLICACAO_HTML).exists():
        frag = Path(REPLICACAO_HTML).read_text(encoding="utf-8")
        return f'<section class="card"><h2>Replicação AD</h2><div class="card-body">{frag}</div></section>'

    # 3) JSON (monta tabela no padrão do site)
    if Path(REPLICACAO_JSON).exists():
        data = json.loads(Path(REPLICACAO_JSON).read_text(encoding="utf-8"))
        payload = data.get("legacy") or data.get("data") or data
        linhas = []
        for ctrl in payload.get("detalhes", {}).get("controladores", []):
            linhas.append(
                "<tr>"
                f"<td>{html.escape(str(ctrl.get('nome','')))}</td>"
                f"<td>{html.escape(str(ctrl.get('latencia','')))}</td>"
                f"<td>{html.escape(str(ctrl.get('sucesso_total','')))}</td>"
                f"<td>{html.escape(str(ctrl.get('erros','')))}</td>"
                "</tr>"
            )
        tabela = (
            "<table class='tabela'><thead><tr>"
            "<th>Servidor</th><th>Latência</th><th>SucessoTotal</th><th>Erros</th>"
            "</tr></thead><tbody>" + "".join(linhas) + "</tbody></table>"
        )
        return f'<section class="card"><h2>Replicação AD</h2><div class="card-body">{tabela}</div></section>'

    # 4) Fallback
    return (
        '<section class="card"><h2>Replicação AD</h2>'
        '<div class="card-body error">Arquivo não encontrado.</div></section>'
    )


# Configuração para Windows - força UTF-8
if sys.platform == "win32":
    import codecs
    import locale
    
    # Tenta configurar UTF-8
    try:
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.detach())
    except:
        # Se falhar, usa print seguro sem emojis
        pass

# Função para print seguro (sem emojis no Windows)
def safe_print(message):
    """Print seguro que funciona no Windows"""
    try:
        print(message)
    except UnicodeEncodeError:
        # Remove emojis e caracteres especiais
        import re
        clean_message = re.sub(r'[^\x00-\x7F]+', '[EMOJI]', message)
        print(clean_message)

# Importa as configurações dinâmicas
from config import (
    CONEXOES_FILE, REGIONAL_HTMLS_DIR, GPS_HTML, REPLICACAO_HTML, 
    UNIFI_HTML, DASHBOARD_FINAL, DASHBOARD_FINAL_ORIGINAL, ensure_directories, get_regional_html_path,
    validate_config, PROJECT_ROOT, RELATORIO_PREVENTIVA_DIR
)

# === VALIDAÇÃO E INICIALIZAÇÃO ===
# Valida as configurações antes de continuar
config_errors = validate_config()
if config_errors:
    print("[ERRO] Erros de configuração encontrados:")
    for error in config_errors:
        print(f"   - {error}")
    sys.exit(1)

# Garante que os diretórios necessários existem
ensure_directories()

safe_print(f"[INFO] Usando diretório do projeto: {PROJECT_ROOT}")
safe_print(f"[INFO] Arquivos serão salvos em: {DASHBOARD_FINAL.parent}")
safe_print(f"[INFO] Arquivo de conexões: {CONEXOES_FILE}")
print()

# === DATA E HORA DA EXECUÇÃO ===
# Obtém a data e hora atual para exibir no dashboard
data_execucao = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

# === 1. EXECUTA CHEKLISTS DAS REGIONAIS ===
def _carregar_servidores_do_txt_legado():
    conteudo = CONEXOES_FILE.read_text(encoding="utf-8")
    blocos = re.split(r"\n\s*\n", conteudo.strip())
    servidores = []

    for bloco in blocos:
        nome_match = re.search(r"Nome:\s*(.+)", bloco, re.IGNORECASE)
        tipo_match = re.search(r"Tipo:\s*(\w+)", bloco, re.IGNORECASE)
        ip_match = re.search(r"IP:\s*([\d\.]+)", bloco, re.IGNORECASE)
        user_match = re.search(r"Usuario:\s*(\S+)", bloco, re.IGNORECASE)
        pass_match = re.search(r"Senha:\s*(\S+)", bloco, re.IGNORECASE)

        if all([nome_match, tipo_match, ip_match, user_match, pass_match]):
            servidores.append({
                'nome': nome_match.group(1).strip(),
                'tipo': tipo_match.group(1).strip().lower(),
                'ip': ip_match.group(1).strip(),
                'usuario': user_match.group(1).strip(),
                'senha': pass_match.group(1).strip(),
                'ativo': True,
            })

    return servidores


def _carregar_servidores_da_estrutura():
    estrutura_path = PROJECT_ROOT / "estrutura_regionais.json"
    if not estrutura_path.exists():
        return []

    data = json.loads(estrutura_path.read_text(encoding="utf-8"))
    servidores = []

    for regional in (data.get("regionais") or {}).values():
        regional_nome = (regional.get("nome") or "").strip()
        if not regional_nome:
            continue

        for servidor in regional.get("servidores", []):
            if not servidor.get("ativo", True):
                continue

            tipo = (servidor.get("tipo") or "").strip().lower()
            ip = (servidor.get("ip") or "").strip()
            usuario = (servidor.get("usuario") or "").strip()
            senha = str(servidor.get("senha") or "").strip()

            if not all([tipo, ip, usuario, senha]):
                continue

            servidores.append({
                'nome': regional_nome,
                'tipo': tipo,
                'ip': ip,
                'usuario': usuario,
                'senha': senha,
                'ativo': True,
                'servidor_nome': (servidor.get('nome') or '').strip(),
                'regional_codigo': (regional.get('codigo') or '').strip(),
            })

    return servidores


def _carregar_servidores_configurados():
    try:
        servidores_estrutura = _carregar_servidores_da_estrutura()
        if servidores_estrutura:
            print(f"[INFO] {len(servidores_estrutura)} servidores carregados de estrutura_regionais.json")
            return servidores_estrutura
        print("[INFO] estrutura_regionais.json encontrado, mas sem servidores ativos válidos")
    except Exception as e:
        print(f"[AVISO] Erro ao carregar estrutura_regionais.json: {e}")

    try:
        from gerenciar_servidores import GerenciadorServidores
        gerenciador = GerenciadorServidores()
        servidores_sistema = gerenciador.listar_servidores()
        if servidores_sistema:
            print(f"[INFO] {len(servidores_sistema)} servidores carregados do sistema de gerenciamento")
            return servidores_sistema
    except Exception as e:
        print(f"[AVISO] Erro ao carregar gerenciador de servidores: {e}")

    print("[INFO] Usando método legado via Conexoes.txt...")
    return _carregar_servidores_do_txt_legado()


def _contar_total_regionais_cadastradas():
    estrutura_path = PROJECT_ROOT / "estrutura_regionais.json"
    if estrutura_path.exists():
        try:
            data = json.loads(estrutura_path.read_text(encoding="utf-8"))
            return len((data.get("regionais") or {}).keys())
        except Exception as e:
            print(f"[AVISO] Erro ao contar regionais em estrutura_regionais.json: {e}")

    return len({(servidor.get("nome") or "").strip().upper() for servidor in servidores_configurados if (servidor.get("nome") or "").strip()})


def _normalizar_link_texto(valor):
    return re.sub(r"[^A-Z0-9]+", "", str(valor or "").strip().upper())


def _normalizar_link_ip(valor):
    return str(valor or "").strip().split()[0]


def _extrair_chave_regional(valor):
    texto = str(valor or "").strip().upper()
    if not texto:
        return "N/A"

    # Padrão mais comum nas regionais/sedes: V030, T018, RGS, etc.
    match = re.search(r"\b([A-Z]\d{3})\b", texto)
    if match:
        return match.group(1)

    return texto


def _extrair_regional_vpn(nome_tunel):
    texto = str(nome_tunel or "").strip().upper()
    if not texto:
        return "N/A"

    # Exemplos:
    # T010_MOTUS_01 -> T010
    # T043_PERNAMB01 -> T043
    # Agrupa por código regional para consolidar todos os túneis da mesma regional.
    match = re.match(r"^([A-Z]\d{3})", texto)
    if match:
        return match.group(1)

    return _extrair_chave_regional(texto)


def _extrair_nome_exibicao_regional_vpn(nome_tunel):
    texto = str(nome_tunel or "").strip().upper()
    if not texto:
        return "REGIONAL"

    # Exemplo: V049_MACAELC_01 -> MACAELC
    # Exemplo: T043_PERNAMB01 -> PERNAMB
    match = re.match(r"^[A-Z]\d{3}_?(.+)$", texto)
    sufixo = match.group(1) if match else texto
    sufixo = sufixo.strip("_-")
    if not sufixo:
        return "REGIONAL"

    partes = [p for p in sufixo.split("_") if p]
    if not partes:
        return "REGIONAL"

    # Remove marcador genérico de início (REG/REGIONAL), ex.: REG_RJ -> RJ
    if partes[0] in {"REG", "REGIONAL"} and len(partes) > 1:
        partes = partes[1:]

    primeira_parte = partes[0]
    nome_limpo = re.sub(r"\d+$", "", primeira_parte).strip("_-")
    return nome_limpo or primeira_parte or "REGIONAL"


def _normalizar_texto_regional(valor):
    texto = str(valor or "").strip().upper()
    if not texto:
        return ""

    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = re.sub(r"[^A-Z0-9]+", "", texto)
    return texto


def _remover_prefixo_regional(valor):
    texto = str(valor or "").strip().upper()
    return re.sub(r"^(RG|REG|REGIONAL)[_\s\-]*", "", texto).strip()


def _gerar_tokens_regional(valor):
    texto = str(valor or "").strip().upper()
    if not texto:
        return set()

    tokens = set()
    candidatos = [texto, _remover_prefixo_regional(texto)]
    for candidato in candidatos:
        normalizado = _normalizar_texto_regional(candidato)
        if normalizado:
            tokens.add(normalizado)

        partes = [p for p in re.split(r"[_\s\-/&]+", candidato) if p]
        partes = [p for p in partes if p not in {"RG", "REG", "REGIONAL", "DE", "DO", "DA", "DOS", "DAS", "E"}]

        for parte in partes:
            parte_norm = _normalizar_texto_regional(parte)
            if parte_norm:
                tokens.add(parte_norm)

        if partes:
            sigla = "".join(p[0] for p in partes if p and p[0].isalpha())
            sigla_norm = _normalizar_texto_regional(sigla)
            if len(sigla_norm) >= 2:
                tokens.add(sigla_norm)

    return {t for t in tokens if t}


def _carregar_indice_regionais():
    estrutura_path = PROJECT_ROOT / "estrutura_regionais.json"
    if not estrutura_path.exists():
        return []

    try:
        data = json.loads(estrutura_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    indice = []
    for chave, dados in (data.get("regionais") or {}).items():
        nome = str((dados or {}).get("nome") or chave).strip()
        nome_sem_prefixo = _remover_prefixo_regional(nome).replace("_", " ").strip()
        nome_exibicao = nome_sem_prefixo or nome

        tokens = set()
        tokens.update(_gerar_tokens_regional(chave))
        tokens.update(_gerar_tokens_regional(nome))

        indice.append({
            "chave": chave,
            "nome_exibicao": nome_exibicao,
            "tokens": tokens,
        })

    return indice


def _mapear_regional_vpn(nome_exibicao_vpn, codigo_vpn, indice_regionais):
    if not indice_regionais:
        return None

    candidatos = []
    candidatos.extend(_gerar_tokens_regional(nome_exibicao_vpn))
    candidatos.extend(_gerar_tokens_regional(codigo_vpn))
    candidatos = [c for c in candidatos if c]

    # 1) Match exato por token
    for cand in candidatos:
        for reg in indice_regionais:
            if cand in reg["tokens"]:
                return reg

    # 2) Match aproximado por contenção (evita perder abreviações simples)
    melhor = None
    melhor_score = 0
    for cand in candidatos:
        if len(cand) < 3:
            continue
        for reg in indice_regionais:
            for token in reg["tokens"]:
                if len(token) < 3:
                    continue
                if cand in token or token in cand:
                    score = min(len(cand), len(token))
                    if score > melhor_score:
                        melhor = reg
                        melhor_score = score

    return melhor


def _mapear_interface_preferida(link_cadastrado):
    """Mapeia nomes lógicos/provedores para nomes reais de interface no Fortigate."""
    interface_explicita = str(link_cadastrado.get("interface_fortigate") or "").strip().lower()
    if interface_explicita:
        return interface_explicita

    nome = _normalizar_link_texto(link_cadastrado.get("nome"))
    provedor = _normalizar_link_texto(link_cadastrado.get("provedor"))

    # WAN11 costuma ser nomenclatura lógica no cadastro; no Fortigate geralmente é wan2.
    mapeamento_nome = {
        "WAN11": "wan2",
        "WAN2": "wan2",
        "WAN1": "wan1",
    }
    if nome in mapeamento_nome:
        return mapeamento_nome[nome]

    mapeamento_provedor = {
        "MUNDIVOX": "wan2",
    }
    return mapeamento_provedor.get(provedor)


def _carregar_links_cadastrados_fortigate(regiao):
    estrutura_path = PROJECT_ROOT / "estrutura_regionais.json"
    regional_por_regiao = {
        "RJ": "REG_RIO_DE_JANEIRO",
    }

    regional_codigo = regional_por_regiao.get((regiao or "").strip().upper())
    if not regional_codigo or not estrutura_path.exists():
        return []

    try:
        data = json.loads(estrutura_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[AVISO] Erro ao carregar links cadastrados de {regiao}: {e}")
        return []

    regional = (data.get("regionais") or {}).get(regional_codigo) or {}
    return [link for link in regional.get("links", []) if link.get("ativo", True)]


def _mesclar_links_fortigate_com_cadastro(regiao, links_fortigate):
    links_cadastrados = _carregar_links_cadastrados_fortigate(regiao)
    if not links_cadastrados:
        return links_fortigate

    links_fortigate_todos = [dict(link) for link in links_fortigate]
    links_disponiveis = [dict(link) for link in links_fortigate]
    links_mesclados = []

    for link_cadastrado in links_cadastrados:
        indice_match = None
        nome_cadastrado = _normalizar_link_texto(link_cadastrado.get("nome"))
        provedor_cadastrado = _normalizar_link_texto(link_cadastrado.get("provedor"))
        ip_cadastrado = _normalizar_link_ip(link_cadastrado.get("ip"))
        interface_preferida = _mapear_interface_preferida(link_cadastrado)

        if interface_preferida:
            for indice, link_fortigate in enumerate(links_disponiveis):
                if str(link_fortigate.get("nome") or "").strip().lower() == interface_preferida:
                    indice_match = indice
                    break

        for indice, link_fortigate in enumerate(links_disponiveis):
            if _normalizar_link_texto(link_fortigate.get("nome")) == nome_cadastrado:
                indice_match = indice
                break

        if indice_match is None:
            for indice, link_fortigate in enumerate(links_disponiveis):
                if _normalizar_link_texto(link_fortigate.get("alias")) == provedor_cadastrado:
                    indice_match = indice
                    break

        if indice_match is None:
            for indice, link_fortigate in enumerate(links_disponiveis):
                if _normalizar_link_ip(link_fortigate.get("ip")) == ip_cadastrado:
                    indice_match = indice
                    break

        link_fortigate = links_disponiveis.pop(indice_match) if indice_match is not None else {}
        if not link_fortigate and interface_preferida:
            for item in links_fortigate_todos:
                if str(item.get("nome") or "").strip().lower() == interface_preferida:
                    # Reuso intencional para links lógicos (ex.: WAN11) que compartilham interface física.
                    link_fortigate = dict(item)
                    break

        link_mesclado = dict(link_fortigate)
        link_mesclado["interface_monitorada"] = link_fortigate.get("nome")
        link_mesclado["interface_esperada"] = interface_preferida
        link_mesclado["match_confiavel"] = bool(link_fortigate)
        link_mesclado["nome"] = (link_cadastrado.get("nome") or link_fortigate.get("nome") or "N/A").strip()
        link_mesclado["alias"] = (link_cadastrado.get("provedor") or link_fortigate.get("alias") or "").strip()
        link_mesclado["ip"] = ip_cadastrado or link_fortigate.get("ip", "N/A")
        link_mesclado["status"] = link_fortigate.get("status", link_cadastrado.get("status", "offline"))
        link_mesclado["velocidade"] = link_fortigate.get("velocidade", "N/A")
        link_mesclado["tipo"] = link_fortigate.get("tipo", "N/A")
        link_mesclado["estatisticas"] = link_fortigate.get("estatisticas") or {}
        link_mesclado["ultima_verificacao"] = link_fortigate.get("ultima_verificacao") or link_cadastrado.get("ultima_verificacao")
        links_mesclados.append(link_mesclado)

    # Com cadastro definido, priorizamos o conjunto cadastrado para evitar duplicações no dashboard.
    return links_mesclados


def _formatar_nome_link_dashboard(link):
    nome = str(link.get("nome") or "").strip()
    alias = str(link.get("alias") or "").strip()
    if nome and alias and _normalizar_link_texto(nome) != _normalizar_link_texto(alias):
        return f"{nome} - {alias}"
    return nome or alias or "N/A"


servidores_configurados = _carregar_servidores_configurados()

regionais_processadas = {}


def _regional_html_indicates_error(file_content):
    lowered = file_content.lower()
    error_markers = [
        "[error]",
        "erro ao ",
        "erro no ",
        "erro inesperado",
        "arquivo não encontrado",
        "falha ao ",
        "timed out",
        "connection to",
        "connection aborted",
        "connectionreseterror",
    ]
    return any(marker in lowered for marker in error_markers)

# Processa cada servidor configurado
for servidor in servidores_configurados:
    # Pula servidores inativos
    if not servidor.get('ativo', True):
        continue
    
    nome = servidor['nome']
    tipo = servidor['tipo']
    ip = servidor['ip']
    usuario = servidor['usuario']
    senha = servidor['senha']
    html_path = get_regional_html_path(nome)

    current_regional_html_content = ""
    has_error_for_regional = False

    # Executa o script de checklist apropriado baseado no 'tipo'
    try:
        if tipo == "idrac":
            print(f"[EXEC] Coletando {nome} ({ip}) - iDRAC")
            chelist_path = PROJECT_ROOT / "Chelist.py"
            subprocess.run(["python", str(chelist_path), ip, usuario, senha, str(html_path)], 
                         check=True, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        elif tipo == "ilo":
            print(f"[EXEC] Coletando {nome} ({ip}) - iLO")
            ilo_path = PROJECT_ROOT / "iLOcheck.py"
            subprocess.run(["python", str(ilo_path), ip, usuario, senha, str(html_path)], 
                         check=True, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        else:
            # Trata tipos desconhecidos escrevendo uma mensagem de erro no arquivo HTML
            current_regional_html_content = f"""
            <div class="error-container">
                <div class="error-icon">[ERRO]</div>
                <div class="error-title">Tipo desconhecido</div>
                <div class="error-message">Tipo: {tipo}</div>
            </div>
            """
            has_error_for_regional = True
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(current_regional_html_content)
    except subprocess.CalledProcessError as e:
        error_details = f"Código de saída: {e.returncode}"
        if hasattr(e, 'stdout') and e.stdout:
            error_details += f"\nSaída: {e.stdout}"
        if hasattr(e, 'stderr') and e.stderr:
            error_details += f"\nErro: {e.stderr}"
        
        print(f"[ERRO] Erro ao executar script para {nome} ({ip}): {error_details}")
        
        # Se o subprocess falhar, marca como erro e escreve uma mensagem de erro genérica
        current_regional_html_content = f"""
        <div class="error-container">
            <div class="error-icon">[ERROR]</div>
            <div class="error-title">Erro ao executar script</div>
            <div class="error-message">Regional: {nome}<br>IP: {ip}<br>Erro: {error_details}</div>
        </div>
        """
        has_error_for_regional = True
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(current_regional_html_content)
    except Exception as e:
        print(f"[ERRO] Erro inesperado para {nome} ({ip}): {e}")
        current_regional_html_content = f"""
        <div class="error-container">
            <div class="error-icon">[ERROR]</div>
            <div class="error-title">Erro inesperado</div>
            <div class="error-message">Regional: {nome}<br>IP: {ip}<br>Erro: {str(e)}</div>
        </div>
        """
        has_error_for_regional = True
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(current_regional_html_content)

    # Após tentar executar o subprocess ou tratar tipo desconhecido/erro de subprocess,
    # lê o conteúdo do arquivo HTML gerado se ele existir.
    # Este passo é crucial para capturar erros escritos pelos próprios Chelist.py/iLOcheck.py.
    if html_path.exists():
        file_content = html_path.read_text(encoding="utf-8")
        # Verifica indicadores de falha operacional no conteúdo do arquivo gerado.
        if _regional_html_indicates_error(file_content):
            has_error_for_regional = True
        current_regional_html_content = file_content
    else:
        # Se o arquivo não existir, definitivamente é um erro
        current_regional_html_content = """
        <div class="error-container">
            <div class="error-icon">[ERROR]</div>
            <div class="error-title">Erro ao gerar HTML</div>
            <div class="error-message">Arquivo não encontrado</div>
        </div>
        """
        has_error_for_regional = True

    regional_key = nome.strip().upper()
    regional_data = regionais_processadas.setdefault(
        regional_key,
        {
            "nome": nome,
            "has_error": False,
            "server_blocks": [],
        },
    )
    regional_data["has_error"] = regional_data["has_error"] or has_error_for_regional
    regional_data["server_blocks"].append(
        f"""
        <div class="regional-server-block" style="margin-bottom: 24px;">
            <div style="font-size: 0.95rem; font-weight: 700; color: #4a5568; margin-bottom: 12px;">
                {html.escape(tipo.upper())} - {html.escape(ip)}
            </div>
            {current_regional_html_content}
        </div>
        """
    )

blocos_html_regionais_with_status = []
servidores_online_total = 0
servidores_offline_total = 0
regionais_servidor_status = {}
for regional_data in regionais_processadas.values():
    dados_regional = regionais_servidor_status.setdefault(regional_data["nome"].strip().upper(), {"online": 0, "offline": 0})
    for bloco in regional_data.get("server_blocks", []):
        if _regional_html_indicates_error(bloco):
            servidores_offline_total += 1
            dados_regional["offline"] += 1
        else:
            servidores_online_total += 1
            dados_regional["online"] += 1

    regional_open_attr = ""
    regional_status = "offline" if regional_data["has_error"] else "online"
    regional_html_block = f"""
    <details class="regional-item" data-status="{regional_status}"{regional_open_attr}>
        <summary><strong>{regional_data['nome']}</strong></summary>
        <div class="regional-content">
            {''.join(regional_data['server_blocks'])}
        </div>
    </details>
    """
    blocos_html_regionais_with_status.append((regional_html_block, regional_data["has_error"]))

# === 3. EXECUTA REPLICAÇÃO AD ===
print("[EXEC] Executando verificação de replicação AD...")
try:
    # Executa o script PowerShell para verificação de replicação AD
    env_replicacao = os.environ.copy()
    env_replicacao["AUTOMACAO_SKIP_REPL_BROWSER"] = "1"
    subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", "Replicacao_Servers.ps1"],
        check=True,
        env=env_replicacao,
    )
except subprocess.CalledProcessError:
    print("[ERRO] Erro ao executar Replicacao_Servers.ps1")

# === 4. EXECUTA COLETA DAS APs UNIFI ===
print("[EXEC] Coletando informações das APs UniFi...")
try:
    # Executa o script Python para coletar informações das APs UniFi
    subprocess.run(["python", "Unifi.Py"], check=True)
except subprocess.CalledProcessError:
    print("[ERRO] Erro ao executar Unifi.py")

# === 5. EXECUTA VERIFICAÇÃO DAS VMs ===
print("[EXEC] Verificando status das Máquinas Virtuais...")
vms_data = []
vms_online = 0
vms_offline = 0
relatorio_vms = ""
try:
    # Carrega VMs do arquivo de dados
    vms_file = PROJECT_ROOT / "data" / "vms.json"
    if vms_file.exists():
        import json
        with open(vms_file, 'r', encoding='utf-8') as f:
            vms_configuradas = json.load(f)
    else:
        vms_configuradas = []
    
    from vm_manager import verificar_vm_online
    
    for vm in vms_configuradas:
        try:
            print(f"[EXEC] Verificando VM {vm['name']} ({vm['ip']})")
            
            # Verifica se a VM está online
            vm_online = verificar_vm_online(vm['ip'])
            
            vm_info = {
                'name': vm['name'],
                'ip': vm['ip'],
                'regional': vm.get('regional', 'N/A'),
                'username': vm.get('username', 'N/A'),
                'description': vm.get('description', 'N/A'),
                'last_check': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            if vm_online:
                vms_online += 1
                vm_info['status'] = "online"
                
                # Se a VM está online, gera relatório detalhado
                print(f"[EXEC] Gerando relatório detalhado da VM {vm['name']}...")
                from vm_manager import gerar_relatorio_simples
                
                relatorio = gerar_relatorio_simples(
                    vm['ip'], 
                    vm.get('username', ''), 
                    vm.get('password', '')
                )
                
                if relatorio.get('success', False):
                    print(f"[OK] Relatório detalhado gerado para VM {vm['name']}")
                    vm_info['relatorio_detalhado'] = relatorio
                else:
                    print(f"[WARN] Falha ao gerar relatório detalhado: {relatorio.get('message', 'Erro desconhecido')}")
                    vm_info['relatorio_erro'] = relatorio.get('message', 'Erro desconhecido')
            else:
                vms_offline += 1
                vm_info['status'] = "offline"
                
            vms_data.append(vm_info)
            
        except Exception as e:
            print(f"[ERRO] Erro ao verificar VM {vm['name']}: {e}")
            vms_offline += 1
            vms_data.append({
                'name': vm['name'],
                'ip': vm['ip'],
                'regional': vm.get('regional', 'N/A'),
                'status': 'error',
                'error': str(e),
                'last_check': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
    
    # Gera HTML detalhado das VMs
    relatorio_vms = "<div class='vms-container'>"
    
    for vm in vms_data:
        status_class = "success" if vm['status'] == 'online' else "danger"
        
        relatorio_vms += f"""
        <div class="vm-item mb-4" data-status="{vm['status']}">
            <div class="card">
                <div class="card-header bg-{status_class} text-white">
                    <h4 class="mb-0">[SERVER] {vm['name']}</h4>
                    <small>{vm.get('description', 'N/A')}</small>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-6">
                            <h6> Informações Básicas</h6>
                            <p><strong>IP:</strong> {vm['ip']}</p>
                            <p><strong>Regional:</strong> {vm['regional']}</p>
                            <p><strong>Status:</strong> <span class="badge badge-{status_class}">{vm['status'].upper()}</span></p>
                            <p><strong>Usuário:</strong> {vm.get('username', 'N/A')}</p>
                            <p><strong>Última verificação:</strong> {vm['last_check']}</p>
                            {f"<p><strong>[ERROR] Erro:</strong> {vm['error']}</p>" if vm.get('error') else ""}
                            {f"<p><strong>[WARN] Erro no relatório:</strong> {vm['relatorio_erro']}</p>" if vm.get('relatorio_erro') else ""}
        """
        
        # Se tem relatório detalhado, inclui as informações
        if vm.get('relatorio_detalhado') and vm['relatorio_detalhado'].get('success'):
            relatorio = vm['relatorio_detalhado']
            
            # Informações do sistema
            sistema = relatorio.get('sistema', {})
            if sistema and not sistema.get('error'):
                relatorio_vms += f"""
                            <p><strong>Sistema Operacional:</strong> {sistema.get('OperatingSystem', 'N/A')}</p>
                            <p><strong>Versão:</strong> {sistema.get('OSVersion', 'N/A')}</p>
                            <p><strong>Uptime:</strong> {sistema.get('Uptime', 'N/A')}</p>
                            <p><strong>Último Boot:</strong> {sistema.get('LastBoot', 'N/A')}</p>
                        </div>
                        <div class="col-md-6">
                            <h6> Recursos do Sistema</h6>
                            <p><strong>Processadores:</strong> {sistema.get('Processors', 'N/A')}</p>
                            <p><strong>Memória:</strong> {sistema.get('Memory', 'N/A')}</p>
                            <p><strong>Fabricante:</strong> {sistema.get('Manufacturer', 'N/A')}</p>
                            <p><strong>Modelo:</strong> {sistema.get('Model', 'N/A')}</p>
                            <p><strong>Número de Série:</strong> {sistema.get('SerialNumber', 'N/A')}</p>
                        </div>
                    </div>
                """
                
                # Informações de discos
                discos = relatorio.get('discos', [])
                if discos and not (len(discos) == 1 and discos[0].get('error')):
                    relatorio_vms += """
                    <div class="row mt-3">
                        <div class="col-12">
                            <h6> Discos e Armazenamento</h6>
                            <div class="table-responsive">
                                <table class="table table-sm table-striped">
                                    <thead>
                                        <tr>
                                            <th>Drive</th>
                                            <th>Volume</th>
                                            <th>Espaço Total</th>
                                            <th>Espaço Livre</th>
                                            <th>Espaço Usado</th>
                                            <th>% Usado</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                    """
                    for disco in discos:
                        if not disco.get('error'):
                            percent_usado = disco.get('PercentUsed', 0)
                            try:
                                percent_usado = float(percent_usado)
                                cor_uso = 'success' if percent_usado < 70 else 'warning' if percent_usado < 90 else 'danger'
                            except:
                                cor_uso = 'secondary'
                                percent_usado = 'N/A'
                            
                            relatorio_vms += f"""
                                            <tr>
                                                <td><strong>{disco.get('Drive', 'N/A')}</strong></td>
                                                <td>{disco.get('VolumeName', 'N/A')}</td>
                                                <td>{disco.get('TotalSpace', 'N/A')}</td>
                                                <td>{disco.get('FreeSpace', 'N/A')}</td>
                                                <td>{disco.get('UsedSpace', 'N/A')}</td>
                                                <td><span class="badge badge-{cor_uso}">{percent_usado}%</span></td>
                                            </tr>
                            """
                    relatorio_vms += """
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                    """
                
                # Serviços
                servicos = relatorio.get('servicos', [])
                if servicos and not (len(servicos) == 1 and servicos[0].get('error')):
                    servicos_rodando = [s for s in servicos if s.get('Status') == 'Running' and not s.get('error')]
                    servicos_parados = [s for s in servicos if s.get('Status') == 'Stopped' and s.get('StartMode') == 'Auto' and not s.get('error')]
                    
                    relatorio_vms += f"""
                    <div class="row mt-3">
                        <div class="col-md-6">
                            <h6>[OK] Serviços Ativos ({len(servicos_rodando)})</h6>
                    """
                    if servicos_rodando:
                        relatorio_vms += "<ul class='list-group list-group-flush' style='max-height: 200px; overflow-y: auto;'>"
                        for servico in servicos_rodando[:15]:  # Mostra apenas os primeiros 15
                            relatorio_vms += f"<li class='list-group-item py-1'><small>[OK] {servico.get('DisplayName', servico.get('Name', 'N/A'))}</small></li>"
                        if len(servicos_rodando) > 15:
                            relatorio_vms += f"<li class='list-group-item py-1'><small><em>... e mais {len(servicos_rodando)-15} serviços</em></small></li>"
                        relatorio_vms += "</ul>"
                    else:
                        relatorio_vms += "<p class='text-muted'><small>Nenhum serviço ativo encontrado</small></p>"
                    
                    relatorio_vms += f"""
                        </div>
                        <div class="col-md-6">
                            <h6>[WARN] Serviços Parados ({len(servicos_parados)})</h6>
                    """
                    if servicos_parados:
                        relatorio_vms += "<ul class='list-group list-group-flush' style='max-height: 200px; overflow-y: auto;'>"
                        for servico in servicos_parados[:15]:  # Mostra apenas os primeiros 15
                            relatorio_vms += f"<li class='list-group-item py-1'><small>[ERROR] {servico.get('DisplayName', servico.get('Name', 'N/A'))}</small></li>"
                        if len(servicos_parados) > 15:
                            relatorio_vms += f"<li class='list-group-item py-1'><small><em>... e mais {len(servicos_parados)-15} serviços</em></small></li>"
                        relatorio_vms += "</ul>"
                    else:
                        relatorio_vms += "<p class='text-success'><small>[OK] Todos os serviços automáticos estão funcionando</small></p>"
                    
                    relatorio_vms += """
                        </div>
                    </div>
                    """
                
                # Rede
                rede = relatorio.get('rede', [])
                if rede and not (len(rede) == 1 and rede[0].get('error')):
                    relatorio_vms += """
                    <div class="row mt-3">
                        <div class="col-12">
                            <h6>[WEB] Interfaces de Rede</h6>
                            <div class="table-responsive">
                                <table class="table table-sm table-striped">
                                    <thead>
                                        <tr>
                                            <th>Adaptador</th>
                                            <th>Status</th>
                                            <th>Endereço IP</th>
                                            <th>MAC Address</th>
                                            <th>Gateway</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                    """
                    for interface in rede:
                        if not interface.get('error'):
                            status_rede = interface.get('Status', 'Unknown')
                            cor_status = 'success' if 'Up' in status_rede else 'danger'
                            relatorio_vms += f"""
                                            <tr>
                                                <td>{interface.get('Name', 'N/A')}</td>
                                                <td><span class="badge badge-{cor_status}">{status_rede}</span></td>
                                                <td>{interface.get('IPAddress', 'N/A')}</td>
                                                <td>{interface.get('MACAddress', 'N/A')}</td>
                                                <td>{interface.get('DefaultGateway', 'N/A')}</td>
                                            </tr>
                            """
                    relatorio_vms += """
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                    """
                
                # Processos (Top 10)
                processos = relatorio.get('processos', [])
                if processos and not (len(processos) == 1 and processos[0].get('error')):
                    relatorio_vms += """
                    <div class="row mt-3">
                        <div class="col-12">
                            <h6>[UPDATE] Top 15 Processos por CPU</h6>
                            <div class="table-responsive">
                                <table class="table table-sm table-striped">
                                    <thead>
                                        <tr>
                                            <th>Nome</th>
                                            <th>PID</th>
                                            <th>CPU</th>
                                            <th>Memória (MB)</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                    """
                    for processo in processos[:15]:  # Top 15
                        if not processo.get('error'):
                            cpu_value = processo.get('CPU', 0)
                            memory_value = processo.get('Memory', 0)
                            pid_value = processo.get('Id', 'N/A')
                            
                            # Formata os valores
                            cpu_display = f"{cpu_value}" if cpu_value and cpu_value > 0 else "0"
                            memory_display = f"{memory_value}" if memory_value and memory_value > 0 else "0"
                            
                            relatorio_vms += f"""
                                            <tr>
                                                <td><strong>{processo.get('Name', 'N/A')}</strong></td>
                                                <td>{pid_value}</td>
                                                <td>{cpu_display}</td>
                                                <td>{memory_display} MB</td>
                                            </tr>
                            """
                    relatorio_vms += """
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                    """
                
                # Logs do sistema (Últimos 20)
                eventos = relatorio.get('eventos', [])
                if eventos and not (len(eventos) == 1 and eventos[0].get('error')):
                    relatorio_vms += """
                    <div class="row mt-3">
                        <div class="col-12">
                            <h6> Últimos 20 Logs do Sistema</h6>
                            <div class="table-responsive">
                                <table class="table table-sm table-striped">
                                    <thead>
                                        <tr>
                                            <th>Data/Hora</th>
                                            <th>Tipo</th>
                                            <th>Fonte</th>
                                            <th>ID</th>
                                            <th>Mensagem</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                    """
                    for evento in eventos[:20]:  # Últimos 20 logs
                        if not evento.get('error'):
                            entry_type = evento.get('EntryType', 'Information')
                            
                            # Define a cor baseada no tipo do evento
                            if entry_type == 'Error':
                                tipo_badge = 'danger'
                                tipo_icon = '[ERROR]'
                            elif entry_type == 'Warning':
                                tipo_badge = 'warning'
                                tipo_icon = '[WARN]'
                            else:
                                tipo_badge = 'info'
                                tipo_icon = 'ℹ'
                            
                            # Trunca a mensagem se for muito longa
                            mensagem = evento.get('Message', 'N/A')
                            if len(mensagem) > 100:
                                mensagem = mensagem[:100] + "..."
                            
                            relatorio_vms += f"""
                                            <tr>
                                                <td><small>{evento.get('TimeGenerated', 'N/A')}</small></td>
                                                <td><span class="badge badge-{tipo_badge}">{tipo_icon} {entry_type}</span></td>
                                                <td><small>{evento.get('Source', 'N/A')}</small></td>
                                                <td><small>{evento.get('EventID', 'N/A')}</small></td>
                                                <td><small>{mensagem}</small></td>
                                            </tr>
                            """
                    relatorio_vms += """
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                    """
            else:
                # Se não tem informações do sistema, fecha a div básica
                relatorio_vms += """
                        </div>
                    </div>
                """
        else:
            # Se a VM está offline ou sem relatório, fecha a div básica
            relatorio_vms += """
                        </div>
                    </div>
            """
        
        relatorio_vms += """
                </div>
            </div>
        </div>
        """
    
    relatorio_vms += "</div>"
    
except Exception as e:
    print(f"[ERRO] Erro no módulo de VMs: {e}")
    vms_data = []
    relatorio_vms = f"""
    <div class="error-container">
        <div class="error-icon">[ERROR]</div>
        <div class="error-title">Erro no módulo de VMs</div>
        <div class="error-message">{str(e)}</div>
    </div>
    """

# Debug das VMs após processamento
print(f"[CHECK] Debug VMs (após processamento):")
print(f"   - VMs configuradas encontradas: {len(vms_configuradas) if 'vms_configuradas' in locals() else 0}")
print(f"   - VMs processadas: {len(vms_data)}")
print(f"   - VMs Online: {vms_online}")
print(f"   - VMs Offline: {vms_offline}")
if vms_data:
    for vm in vms_data:
        print(f"   - VM: {vm['name']} - Status: {vm['status']}")

# === 6. EXECUTA VERIFICAÇÃO DOS SWITCHES ===
print("[EXEC] Verificando status dos Switches...")
switches_data = []
switches_online = 0
switches_offline = 0
switches_html_content = ""
try:
    from gerenciar_switches import GerenciadorSwitches
    
    gerenciador_switches = GerenciadorSwitches()
    
    # Verifica TODOS os switches para relatório completo
    print("[EXEC] Verificando TODOS os switches (relatório completo)...")
    print("⏳ Isso pode demorar alguns minutos, aguarde...")
    switches_resultados = gerenciador_switches.verificar_todos_switches()
    
    if switches_resultados:
        # O método retorna um dicionário {nome_switch: resultado}
        for nome_switch, resultado in switches_resultados.items():
            status = resultado.get('status', 'offline')
            
            # Busca informações do switch na lista original
            switch_info = None
            for switch in gerenciador_switches.switches:
                if switch.get('host') == nome_switch:
                    switch_info = switch
                    break
            
            if switch_info:
                # Conta switches online/offline
                if status in ['online', 'warning']:
                    switches_online += 1
                    final_status = 'online'
                else:
                    switches_offline += 1
                    final_status = 'offline'
                
                switches_data.append({
                    'name': nome_switch,
                    'ip': switch_info.get('ip', 'N/A'),
                    'regional': switch_info.get('regional', 'N/A'),
                    'status': final_status,
                    'zabbix_status': status,
                    'last_check': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'detalhes': resultado.get('detalhes', {})
                })
        
        # Gera HTML dos switches
        total_switches = len(gerenciador_switches.switches)
        switches_html_content = f"""
        <div class='switches-container'>
            <div class='switches-summary'>
                <h5>[DATA] Relatório Completo dos Switches</h5>
                <div class='switches-metrics'>
                    <div><strong>Total de switches cadastrados:</strong> {total_switches}</div>
                    <div><strong>Switches verificados nesta execução:</strong> {len(switches_data)}</div>
                    <div><strong>Switches Online:</strong> {switches_online}</div>
                    <div><strong>Switches Offline/Warning:</strong> {switches_offline}</div>
                    <div><strong>Cobertura da coleta:</strong> {len(switches_data)}/{total_switches}</div>
                </div>
            </div>
            
            <div class='switches-regionals-panel'>
                <h6>[URL] Resumo por Regional:</h6>
                <div class="switches-regionals">
        """
        
        # Agrupa switches por regional
        regionais_resumo = {}
        for switch in switches_data:
            regional = switch['regional']
            if regional not in regionais_resumo:
                regionais_resumo[regional] = {'online': 0, 'offline': 0, 'total': 0}
            
            regionais_resumo[regional]['total'] += 1
            if switch['status'] == 'online':
                regionais_resumo[regional]['online'] += 1
            else:
                regionais_resumo[regional]['offline'] += 1
        
        # Adiciona resumo por regional
        for regional, dados in regionais_resumo.items():
            taxa = (dados['online']/dados['total']*100) if dados['total'] > 0 else 0
            status_class = "regional-badge-danger" if dados['offline'] > 0 else "regional-badge-success"
            switches_html_content += f"""
                    <div class="regional-badge {status_class}">
                        <strong>{regional}</strong><br>{dados['online']}/{dados['total']} ({taxa:.0f}%)
                    </div>
            """

        regionais_com_switch_offline = sorted(
            [regional for regional, dados in regionais_resumo.items() if dados['offline'] > 0]
        )

        if regionais_com_switch_offline:
            itens_regionais_offline = "".join(
                [f"<li><strong>{regional}</strong> ({regionais_resumo[regional]['offline']} offline)</li>" for regional in regionais_com_switch_offline]
            )
            switches_html_content += f"""
                </div>
                <div id="switches-offline-regionais" class="regional-badge" style="grid-column: 1 / -1; border-left: 6px solid #dd6b20;">
                    <strong>[WARN] Regionais com switch offline:</strong>
                    <ul style="margin:10px 0 0 18px;">
                        {itens_regionais_offline}
                    </ul>
                </div>
                <div class="switches-regionals">
            """
        
        switches_html_content += """
                </div>
            </div>
            <div class="switches-items">
        """
        for switch in switches_data:
            status = switch.get('status', 'offline')
            zabbix_status = switch.get('zabbix_status', 'unknown')
            status_class = "success" if status == 'online' else "danger"
            
            # Adiciona classe warning se o status do Zabbix for warning
            if zabbix_status == 'warning':
                status_class = "warning"
            
            # Informações detalhadas dos problemas
            detalhes = switch.get('detalhes', {})
            problemas = detalhes.get('problemas', []) if isinstance(detalhes, dict) else []
            itens = detalhes.get('itens', []) if isinstance(detalhes, dict) else []
            
            problemas_html = ""
            if problemas:
                problemas_html = f"""
                <div class="mt-2">
                    <strong>[WARN] Problemas encontrados ({len(problemas)}):</strong>
                    <ul class="small">
                        {''.join([f"<li>{problema.get('name', 'Problema desconhecido')}</li>" for problema in problemas[:3]])}
                        {f"<li><em>... e mais {len(problemas)-3} problemas</em></li>" if len(problemas) > 3 else ""}
                    </ul>
                </div>
                """
            
            itens_html = ""
            if itens:
                itens_html = f"""
                <div class="mt-2">
                    <strong>[DATA] Itens monitorados:</strong> {len(itens)} itens
                </div>
                """
            
            switches_html_content += f"""
            <div class="switch-item mb-3" data-status="{status}" data-regional="{switch.get('regional', 'N/A')}">
                <div class="card">
                    <div class="card-header">
                        <div>
                            <h5 class="mb-0">{switch['name']}</h5>
                            <small>ID Zabbix: {detalhes.get('host_id', 'N/A') if isinstance(detalhes, dict) else 'N/A'}</small>
                        </div>
                        <span class="status-badge {status_class}">{status.title()}</span>
                    </div>
                    <div class="card-body">
                        <p><strong>IP:</strong> {switch['ip']}</p>
                        <p><strong>Status Zabbix:</strong> {zabbix_status.title()}</p>
                        <p><strong>Regional:</strong> {switch['regional']}</p>
                        <p><strong>Última verificação:</strong> {switch['last_check']}</p>
                        {problemas_html}
                        {itens_html}
                    </div>
                </div>
            </div>
            """
        switches_html_content += "</div></div>"
        
        if not switches_data:
            switches_html_content = """
            <div class="alert alert-warning">
                <div class="alert-icon">[WARN]</div>
                <div class="alert-title">Nenhum switch encontrado</div>
                <div class="alert-message">Verifique a configuração do Zabbix</div>
            </div>
            """
    else:
        switches_html_content = f"""
        <div class="error-container">
            <div class="error-icon">[ERROR]</div>
            <div class="error-title">Erro ao verificar switches</div>
            <div class="error-message">Erro na conexão com Zabbix ou falha na verificação dos switches</div>
        </div>
        """
        
except Exception as e:
    print(f"[ERRO] Erro no módulo de Switches: {e}")
    switches_html_content = f"""
    <div class="error-container">
        <div class="error-icon">[ERROR]</div>
        <div class="error-title">Erro no módulo de Switches</div>
        <div class="error-message">{str(e)}</div>
    </div>
    """

# Debug dos Switches após processamento
print(f"[CHECK] Debug Switches (após processamento):")
print(f"   - Switches processados: {len(switches_data)}")
print(f"   - Switches Online: {switches_online}")
print(f"   - Switches Offline: {switches_offline}")
if switches_data:
    print(f"   - Primeiros 5 switches:")
    for i, switch in enumerate(switches_data[:5]):
        print(f"     {i+1}. {switch['name']} - Status: {switch['status']} (Zabbix: {switch.get('zabbix_status', 'N/A')})")

# === 7. EXECUTA VERIFICAÇÃO DOS LINKS DE INTERNET ===
print("[EXEC] Verificando Links de Internet...")

links_data = []
links_online = 0
links_offline = 0
links_html_content = ""

try:
    from gerenciar_fortigate import GerenciadorFortigate
    from config import ENV_CONFIG

    fortigates = ENV_CONFIG.get("fortigate")

    if not isinstance(fortigates, dict):
        raise Exception("ENV_CONFIG['fortigate'] deve conter SP/RJ")

    # percorre SP, RJ, etc
    for regiao, cfg in fortigates.items():
        print(f"[EXEC] Fortigate {regiao} ({cfg.get('host')})")

        gerenciador = GerenciadorFortigate(
            host=cfg.get("host"),
            port=cfg.get("port"),
            username=cfg.get("username"),
            password=cfg.get("password"),
        )

        auth_result = gerenciador.autenticar()
        auth_success = auth_result is True or (
            isinstance(auth_result, dict) and auth_result.get("success")
        )

        if not auth_success:
            links_html_content += f"""
            <div class="error-container">
                <div class="error-title">Erro Fortigate {regiao}</div>
                <div class="error-message">Falha na autenticação</div>
            </div>
            """
            continue

        links_info = gerenciador.obter_estatisticas_links()

        if not links_info.get("success"):
            continue

        links_processados = _mesclar_links_fortigate_com_cadastro(regiao, links_info.get("links", []))

        for link in links_processados:
            status = link.get("status", "offline")
            if status == "online":
                links_online += 1
            else:
                links_offline += 1

            links_data.append({
                "regiao": regiao,
                "nome": _formatar_nome_link_dashboard(link),
                "ip": link.get("ip", "N/A"),
                "status": status,
                "velocidade": link.get("velocidade", "N/A"),
                "tipo": link.get("tipo", "N/A"),
                "estatisticas": link.get("estatisticas") or {},
                "interface_monitorada": link.get("interface_monitorada"),
                "interface_esperada": link.get("interface_esperada"),
                "match_confiavel": bool(link.get("match_confiavel", True)),
                "ultima_verificacao": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })



    # ===== HTML =====
    links_por_regiao = {}
    for link in links_data:
        regiao = str(link.get("regiao") or "N/A").strip().upper()
        links_por_regiao.setdefault(regiao, []).append(link)

    ordem_preferida_regioes = ["SP", "RJ"]
    regioes_ordenadas = [reg for reg in ordem_preferida_regioes if reg in links_por_regiao]
    regioes_ordenadas.extend(sorted(reg for reg in links_por_regiao if reg not in ordem_preferida_regioes))

    links_html_content = "<div class='links-container'>"

    if not links_data:
        links_html_content += """
        <div class="error-container">
            <div class="error-title">Sem dados de links</div>
            <div class="error-message">Nenhum link foi retornado pelos Fortigates no momento.</div>
        </div>
        """
    else:
        links_html_content += "<div class='links-overview'>"
        for regiao in regioes_ordenadas:
            links_regiao = links_por_regiao[regiao]
            online_regiao = sum(1 for item in links_regiao if item.get("status") == "online")
            offline_regiao = len(links_regiao) - online_regiao
            classe_regional = "sp" if regiao == "SP" else "rj" if regiao == "RJ" else "other"
            links_html_content += f"""
            <div class="regional-chip {classe_regional}">
                <div class="regional-chip-header">Regional {regiao}</div>
                <div class="regional-chip-stats">
                    <span class="ok">Online: {online_regiao}</span>
                    <span class="sep">|</span>
                    <span class="alert">Offline: {offline_regiao}</span>
                </div>
            </div>
            """
        links_html_content += "</div>"

        links_html_content += "<div class='links-regions-grid'>"
        for regiao in regioes_ordenadas:
            links_regiao = links_por_regiao[regiao]
            online_regiao = sum(1 for item in links_regiao if item.get("status") == "online")
            offline_regiao = len(links_regiao) - online_regiao

            links_html_content += f"""
            <section class="links-region-block" id="links-{regiao.lower()}">
                <header class="links-region-header">
                    <h4>{regiao}</h4>
                    <div class="links-region-counts">
                        <span class="ok">Online: {online_regiao}</span>
                        <span class="alert">Offline: {offline_regiao}</span>
                    </div>
                </header>
                <div class="links-region-items">
            """

            for link in links_regiao:
                status_class = "success" if link["status"] == "online" else "danger"
                estat = link["estatisticas"]
                match_confiavel = bool(link.get("match_confiavel", True))
                monitorada = link.get("interface_monitorada") or "N/A"
                esperada = link.get("interface_esperada") or "não definida"
                download = estat.get('bandwidth_in_readable', 'N/A')
                upload = estat.get('bandwidth_out_readable', 'N/A')

                if not match_confiavel:
                    download = "N/A (sem correspondência da interface)"
                    upload = "N/A (sem correspondência da interface)"

                links_html_content += f"""
                    <div class="link-item" data-status="{link['status']}">
                        <div class="card">
                            <div class="card-header bg-{status_class}">
                                <div>
                                    <h5 class="mb-0">{link['nome']}</h5>
                                    <small>IP: {link['ip']}</small>
                                </div>
                                <span class="status-pill {status_class}">{link['status'].title()}</span>
                            </div>
                            <div class="card-body">
                                <p class="link-monitor"><strong>Interface monitorada:</strong> {monitorada} <span class="link-monitor-note">(esperada: {esperada})</span></p>
                                <div class="link-meta-grid">
                                    <p><strong>Tipo:</strong> {link['tipo']}</p>
                                    <p><strong>Velocidade:</strong> {link['velocidade']}</p>
                                </div>
                                <hr>
                                <div class="link-bandwidth-grid">
                                    <p><strong>Download:</strong> {download}</p>
                                    <p><strong>Upload:</strong> {upload}</p>
                                </div>
                                <p class="link-last-check"><strong>Última verificação:</strong> {link['ultima_verificacao']}</p>
                            </div>
                        </div>
                    </div>
                """

            links_html_content += """
                </div>
            </section>
            """

        links_html_content += "</div>"

    links_html_content += "</div>"

except Exception as e:
    print(f"[ERRO] Erro no módulo de Links: {e}")
    links_html_content = f"""
    <div class="error-container">
        <div class="error-title">Erro no módulo de Links</div>
        <div class="error-message">{e}</div>
    </div>
    """

# === 8. CARREGA HTMLs GERADOS ===
# Carrega o conteúdo dos arquivos HTML gerados. Se um arquivo não existir, fornece uma mensagem de erro.
# --- GPS: garante placeholder e tenta gerar o print ANTES de ler o arquivo ---
from gps_print import ensure_gps_placeholder, gerar_print_gps_amigo, gerar_print_saturno_portal, gerar_print_appgate
ensure_gps_placeholder()
try:
    gerar_print_gps_amigo()
    print("[GPS] Print gerado com sucesso.")
except Exception as e:
    print("[GPS] Falha ao gerar print:", e)

try:
    gerar_print_saturno_portal()
    print("[PRINT-REDE] Prints gerados com sucesso.")
except Exception as e:
    print("[PRINT-REDE] Falha ao gerar prints:", e)

try:
    gerar_print_appgate()
    print("[APPGATE] Print gerado com sucesso.")
except Exception as e:
    print("[APPGATE] Falha ao gerar print:", e)

# (opcional) monta o card para uso em outros lugares, se precisar
gps_section = render_bloco_gps()


# Se você injeta o card no topo, garanta que ele é montado DEPOIS de gerar o print:
gps_section = render_bloco_gps()


# Use sempre o helper que garante imagem inline (HTML ou PNG)
gps_html = _montar_gps_html()
print_rede_html = _montar_print_rede_html()
appgate_html = _montar_appgate_html()


rep_html = REPLICACAO_HTML.read_text(encoding="utf-8") if REPLICACAO_HTML.exists() else """
<div class="error-container">
    <div class="error-icon">[ERROR]</div>
    <div class="error-title">Arquivo não encontrado</div>
    <div class="error-message">replsummary.html não encontrado</div>
</div>
"""
# Reconstrói regionais_html a partir dos blocos armazenados com seus status
regionais_html = "".join([block_string for block_string, _ in blocos_html_regionais_with_status])
if not blocos_html_regionais_with_status:
    regionais_html = """
    <div class="error-container">
        <div class="error-icon">[ERROR]</div>
        <div class="error-title">Nenhuma regional processada</div>
        <div class="error-message">Verifique o cadastro das regionais e os servidores ativos em estrutura_regionais.json</div>
    </div>
    """
unifi_html = UNIFI_HTML.read_text(encoding="utf-8") if UNIFI_HTML.exists() else """
<div class="error-container">
    <div class="error-icon">[ERROR]</div>
    <div class="error-title">Arquivo não encontrado</div>
    <div class="error-message">dados_aps_unifi.html não encontrado</div>
</div>
"""

# === 9. KPIs e dados para os gráficos ===
# Calcula KPIs para verificações regionais baseado no status de erro armazenado
total_regionais_cadastradas = _contar_total_regionais_cadastradas()
regionais_ok = sum(1 for _, has_error in blocos_html_regionais_with_status if not has_error)
regionais_erro = sum(1 for _, has_error in blocos_html_regionais_with_status if has_error)
regionais_sem_erro = max(total_regionais_cadastradas - regionais_erro, 0)
regionais_disponibilidade = (regionais_sem_erro / total_regionais_cadastradas * 100) if total_regionais_cadastradas else 0
regionais_servidor_com_offline = regionais_erro
regionais_servidor_sem_offline = regionais_sem_erro


# Debug Regionais
print(f"[CHECK] Debug Regionais:")
print(f"   - Regionais cadastradas: {total_regionais_cadastradas}")
print(f"   - Regionais OK: {regionais_ok}")
print(f"   - Regionais com erro: {regionais_erro}")
print(f"   - Total de blocos processados: {len(blocos_html_regionais_with_status)}")
for i, (_, has_error) in enumerate(blocos_html_regionais_with_status):
    status = "ERRO" if has_error else "OK"
    print(f"   - Regional {i+1}: {status}")

# Determina o status do GPS: sucesso se o HTML embutiu a imagem OU se o PNG foi gerado
def _gps_ok():
    try:
        # 1) HTML com imagem base64
        if GPS_HTML.exists():
            txt = GPS_HTML.read_text(encoding="utf-8", errors="ignore")
            if "data:image/png;base64" in txt:
                return True
        # 2) PNG físico ao lado do print_temp.html
        png_path = GPS_HTML.with_name("gps_amigo.png")
        if png_path.exists() and png_path.stat().st_size > 10_000:  # >10KB evita falso-positivo
            return True
    except Exception:
        pass
    return False

gps_ok = _gps_ok()
gps_amigo_ok = gps_ok

def _print_rede_ok():
    try:
        from config import SATURNO_OUTPUT_BASE
        now = datetime.now()
        out_dir = SATURNO_OUTPUT_BASE / f"{now.year}" / _month_abbr_pt_local(now.month) / f"{now.day:02d}"
        png = out_dir / "saturno_wifi.png"
        return png.exists() and png.stat().st_size > 10_000
    except Exception:
        return False

def _print_firewall_ok():
    try:
        if APPGATE_IMG.exists() and APPGATE_IMG.stat().st_size > 10_000:
            return True
        if APPGATE_HTML.exists():
            txt = APPGATE_HTML.read_text(encoding="utf-8", errors="ignore")
            if "data:image/png" in txt or "<img" in txt:
                return True
    except Exception:
        pass
    return False

print_rede_ok = _print_rede_ok()
print_firewall_ok = _print_firewall_ok()
gps_status_display = (
    "<i class='fas fa-check-circle text-green-500'></i> Sucesso"
    if gps_ok else
    "<i class='fas fa-times-circle text-red-500'></i> Erro"
)


# Conta APs online/offline do conteúdo HTML do UniFi
aps_online = unifi_html.count("Online") if "[ERROR]" not in unifi_html else 0
aps_offline = unifi_html.count("Offline") if "[ERROR]" not in unifi_html else 0

# Métrica regional das APs: quantas regionais têm ao menos 1 AP offline
aps_regionais_status = {}
try:
    unifi_json_path = PROJECT_ROOT / "data" / "unifi.json"
    if unifi_json_path.exists():
        unifi_json_data = json.loads(unifi_json_path.read_text(encoding="utf-8"))
        for ap in unifi_json_data.get("aps", []):
            regional_ap = _extrair_chave_regional(ap.get("site"))
            if regional_ap == "N/A":
                continue

            status_ap = str(ap.get("status") or "offline").strip().lower()
            dados_regional = aps_regionais_status.setdefault(regional_ap, {"online": 0, "offline": 0})
            if status_ap == "online":
                dados_regional["online"] += 1
            else:
                dados_regional["offline"] += 1
except Exception as e:
    print(f"[AVISO] Não foi possível calcular APs por regional: {e}")

aps_regionais_total = len(aps_regionais_status)
aps_regionais_com_offline = sum(1 for dados in aps_regionais_status.values() if dados["offline"] > 0)
aps_regionais_sem_offline = max(aps_regionais_total - aps_regionais_com_offline, 0)

# Debug UniFi
print(f"[CHECK] Debug UniFi:")
print(f"   - APs Online: {aps_online}")
print(f"   - APs Offline: {aps_offline}")
print(f"   - Regionais com AP offline: {aps_regionais_com_offline}")
print(f"   - Regionais sem AP offline: {aps_regionais_sem_offline}")
print(f"   - HTML UniFi existe: {UNIFI_HTML.exists()}")
if "[ERROR]" in unifi_html:
    print(f"   - Erro detectado no HTML UniFi")

# === LÓGICA CORRETA DE CONTAGEM BASEADA EM LATÊNCIA E ERRO ===
# Lista de servidores com falha de replicação explícita (erros operacionais)
# Busca por padrões como "58 - ALDEBARAN.Galaxia.local" ou "58 - ELTANIN.Galaxia.local"
replication_errors_list = re.findall(r"\d+\s*-\s*([A-Z0-9\.\-]+\.(?:Galaxia\.)?local)", rep_html, re.IGNORECASE)

# Busca por dados na tabela HTML - padrão mais flexível
# Procura por linhas da tabela que contenham dados de servidor
table_rows = re.findall(r"<tr[^>]*>.*?<td[^>]*>([A-Z0-9\-]+)</td>.*?<td[^>]*>([^<]+)</td>.*?<td[^>]*>([^<]+)</td>.*?<td[^>]*>(\d+)</td>.*?</tr>", rep_html, re.IGNORECASE | re.DOTALL)

# Conta servidores com erro na tabela (coluna Erros > 0)
table_errors = 0
rep_ok = 0

# Processa cada linha da tabela
for servidor, latencia, sucesso_total, erros in table_rows:
    servidor_clean = servidor.strip().upper()
    erros_num = int(erros.strip())
    
    if erros_num > 0:
        table_errors += 1
    else:
        # Verifica se não está na lista de erros operacionais
        servidor_base = servidor_clean.split('.')[0]  # Remove domínio se houver
        is_in_error_list = any(servidor_base in erro.upper() or servidor_clean in erro.upper() for erro in replication_errors_list)
        
        # Conta como OK se não tem erros e não está na lista de erros operacionais
        if not is_in_error_list:
            rep_ok += 1

# Total de erros = erros operacionais + erros da tabela
rep_fail = len(replication_errors_list) + table_errors
rep_total = rep_ok + rep_fail
rep_taxa_ok = (rep_ok / rep_total * 100) if rep_total else 0

# Debug: adiciona informações para troubleshooting
print(f"[CHECK] Debug Replicação AD:")
print(f"   - Servidores OK: {rep_ok}")
print(f"   - Erros operacionais: {len(replication_errors_list)}")
print(f"   - Erros da tabela: {table_errors}")
print(f"   - Total de erros: {rep_fail}")
print(f"   - Total geral: {rep_total}")
if replication_errors_list:
    print(f"   - Lista de erros operacionais: {replication_errors_list}")
print(f"   - Linhas da tabela encontradas: {len(table_rows)}")

# Ensure rep_ok is not negative
if rep_ok < 0:
    rep_ok = 0

# Determine AD replication status display with icons.
if rep_fail == 0:
    rep_status_display = "<i class='fas fa-check-circle text-green-500'></i> Sucesso"
else:
    rep_status_display = "<i class='fas fa-times-circle text-red-500'></i> Erro"

# Debug das novas métricas
print(f"[CHECK] Debug VMs:")
print(f"   - VMs Online: {vms_online}")
print(f"   - VMs Offline: {vms_offline}")
print(f"   - Total de VMs: {len(vms_data)}")
vms_total = len(vms_data)
vms_disponibilidade = (vms_online / vms_total * 100) if vms_total else 0
vms_regionais_status = {}
for vm in vms_data:
    regional_vm = _extrair_chave_regional(vm.get("regional"))
    if regional_vm == "N/A":
        continue
    dados_regional_vm = vms_regionais_status.setdefault(regional_vm, {"online": 0, "offline": 0})
    if vm.get("status") == "online":
        dados_regional_vm["online"] += 1
    else:
        dados_regional_vm["offline"] += 1

vms_regionais_total = len(vms_regionais_status)
vms_regionais_com_offline = sum(1 for dados in vms_regionais_status.values() if dados["offline"] > 0)
vms_regionais_sem_offline = max(vms_regionais_total - vms_regionais_com_offline, 0)

print(f"[CHECK] Debug Switches:")
print(f"   - Switches Online: {switches_online}")
print(f"   - Switches Offline: {switches_offline}")
print(f"   - Total de Switches: {len(switches_data)}")

switches_regionais_status = {}
for switch in switches_data:
    regional_switch = _extrair_chave_regional(switch.get("regional"))
    if regional_switch == "N/A":
        continue

    dados_regional = switches_regionais_status.setdefault(regional_switch, {"online": 0, "offline": 0})
    if switch.get("status") == "online":
        dados_regional["online"] += 1
    else:
        dados_regional["offline"] += 1

switches_regionais_total = len(switches_regionais_status)
switches_regionais_com_offline = sum(1 for dados in switches_regionais_status.values() if dados["offline"] > 0)
switches_regionais_sem_offline = max(switches_regionais_total - switches_regionais_com_offline, 0)
print(f"   - Regionais com switch offline: {switches_regionais_com_offline}")
print(f"   - Regionais sem switch offline: {switches_regionais_sem_offline}")

print(f"[CHECK] Debug Links de Internet:")
print(f"   - Links Online: {links_online}")
print(f"   - Links Offline: {links_offline}")
print(f"   - Total de Links: {len(links_data)}")
links_regionais_monitoradas = len({str(link.get('regiao') or '').strip().upper() for link in links_data if str(link.get('regiao') or '').strip()})
links_total = len(links_data)
links_disponibilidade = (links_online / links_total * 100) if links_total else 0
links_regionais_status = {}
for link in links_data:
    regional_link = _extrair_chave_regional(link.get("regiao"))
    if regional_link == "N/A":
        continue
    dados_regional_link = links_regionais_status.setdefault(regional_link, {"online": 0, "offline": 0})
    if link.get("status") == "online":
        dados_regional_link["online"] += 1
    else:
        dados_regional_link["offline"] += 1

links_regionais_total = len(links_regionais_status)
links_regionais_com_offline = sum(1 for dados in links_regionais_status.values() if dados["offline"] > 0)
links_regionais_sem_offline = max(links_regionais_total - links_regionais_com_offline, 0)

from gps_print import ensure_gps_placeholder, gerar_print_gps_amigo
ensure_gps_placeholder()
try:
    gerar_print_gps_amigo()
except Exception as e:
    print("[GPS] Falha ao gerar print:", e)

from config import GPS_HTML

def render_bloco_gps():
    """Lê o HTML do print e devolve só o conteúdo do <body>."""
    try:
        gps_html_full = GPS_HTML.read_text(encoding="utf-8")
    except FileNotFoundError:
        gps_html = "<div class='error'>Print GPS Amigo não encontrado.</div>"
    else:
        import re
        m = re.search(r"<body[^>]*>(.*?)</body>", gps_html_full, flags=re.IGNORECASE | re.DOTALL)
        gps_html = m.group(1).strip() if m else gps_html_full

    return f"""
    <section class="card">
      <h2>Print GPS Amigo</h2>
      <div class="card-body">
        {gps_html}
      </div>
    </section>
    """




# --- Garante que o print exista no Public (placeholder + tentativa real) ---
# --- GPS: garante arquivo e gera print real ---
from gps_print import ensure_gps_placeholder, gerar_print_gps_amigo
ensure_gps_placeholder()
try:
    gerar_print_gps_amigo()
except Exception as e:
    print("[GPS] Falha ao gerar print:", e)

# Card pronto (usa a função que você já tem na linha 26)
gps_section = render_bloco_gps()

# --- INÍCIO DA LÓGICA DE VPN ---
try:
    # 1. Busca os dados usando seu gerenciador existente
    dados_vpn = gerenciador_fortigate.obter_vpn_ipsec()
    lista_vpns = dados_vpn.get("vpns", []) if dados_vpn and dados_vpn.get("success") else []
    indice_regionais = _carregar_indice_regionais()

    # 2. Calcula os contadores para os KPIs e Gráficos
    vpns_total = len(lista_vpns)
    # Considera 'up' como online, qualquer outra coisa como offline
    vpns_online = sum(1 for v in lista_vpns if v.get('status') == 'up')
    vpns_offline = vpns_total - vpns_online

    # 3. Estrutura por regional usando o nome do túnel (ex.: T010_MOTUS_01)
    vpns_por_regional = {}
    for vpn in lista_vpns:
        tunel = str(vpn.get('tunel') or 'Desconhecido').strip()
        status = 'online' if vpn.get('status') == 'up' else 'offline'
        regional_vpn = _extrair_regional_vpn(tunel)
        nome_exibicao_vpn = _extrair_nome_exibicao_regional_vpn(tunel)

        regional_mapeada = _mapear_regional_vpn(nome_exibicao_vpn, regional_vpn, indice_regionais)
        if regional_mapeada:
            regional = regional_mapeada["chave"]
            nome_exibicao = regional_mapeada["nome_exibicao"]
        else:
            regional = regional_vpn
            nome_exibicao = nome_exibicao_vpn

        dados_regional = vpns_por_regional.setdefault(
            regional,
            {"online": 0, "offline": 0, "tunels": [], "nome_exibicao": nome_exibicao}
        )
        dados_regional[status] += 1
        if not dados_regional.get("nome_exibicao"):
            dados_regional["nome_exibicao"] = nome_exibicao
        dados_regional["tunels"].append({"nome": tunel, "status": status})

    regionais_vpn_ordenadas = sorted(vpns_por_regional.keys())
    regionais_vpn_com_offline = [reg for reg in regionais_vpn_ordenadas if vpns_por_regional[reg]["offline"] > 0]
    regionais_cadastradas_set = {item.get("chave") for item in indice_regionais}
    regionais_vpn_mapeadas = [reg for reg in regionais_vpn_ordenadas if reg in regionais_cadastradas_set]
    regionais_vpn_mapeadas_com_offline = [reg for reg in regionais_vpn_mapeadas if vpns_por_regional[reg]["offline"] > 0]

    vpn_regionais_total = len(regionais_vpn_mapeadas)
    vpn_regionais_com_offline = len(regionais_vpn_mapeadas_com_offline)
    vpn_regionais_sem_offline = max(vpn_regionais_total - vpn_regionais_com_offline, 0)

    if not lista_vpns:
        vpn_html_content = """
        <div class="error-container">
            <div class="error-icon"><i class="fas fa-unlink"></i></div>
            <div class="error-title">Sem dados de túneis VPN</div>
            <div class="error-message">Nenhum túnel foi retornado pelo Fortigate.</div>
        </div>
        """
    else:
        regionais_vpn_exibicao = regionais_vpn_mapeadas if regionais_vpn_mapeadas else regionais_vpn_ordenadas
        resumo_regionais_html = ""
        for regional in regionais_vpn_exibicao:
            dados = vpns_por_regional[regional]
            nome_regional = dados.get("nome_exibicao") or regional
            resumo_regionais_html += f"""
                <div class="vpn-regional-badge {'vpn-regional-alert' if dados['offline'] > 0 else ''}">
                    <strong>{nome_regional}</strong><br>
                    <span class="ok">Online: {dados['online']}</span> |
                    <span class="alert">Offline: {dados['offline']}</span>
                </div>
            """

        cards_tuneis_html = ""
        for regional in regionais_vpn_exibicao:
            dados = vpns_por_regional[regional]
            nome_regional = dados.get("nome_exibicao") or regional
            cards_tuneis_html += f"""
            <div class="vpn-regional-group">
                <h4>{nome_regional}</h4>
            """
            for tunel in dados["tunels"]:
                status_class = 'online' if tunel['status'] == 'online' else 'offline'
                cards_tuneis_html += f"""
                <div class="vpn-tunnel-card vpn-{status_class}" data-status="{status_class}" data-regional="{regional}">
                    <strong>{tunel['nome']}</strong>
                    <span class="vpn-status-pill {status_class}">{status_class.upper()}</span>
                </div>
                """
            cards_tuneis_html += "</div>"

        regionais_offline_html = ""
        regionais_offline_exibicao = [reg for reg in regionais_vpn_exibicao if vpns_por_regional[reg]["offline"] > 0]
        if regionais_offline_exibicao:
            itens = "".join([
                f"<li><strong>{vpns_por_regional[reg].get('nome_exibicao') or reg}</strong> ({vpns_por_regional[reg]['offline']} túnel(is) offline)</li>"
                for reg in regionais_offline_exibicao
            ])
            regionais_offline_html = f"""
            <div id="vpn-offline-regionais" class="vpn-offline-box">
                <strong>[WARN] Regionais com túnel VPN offline:</strong>
                <ul>{itens}</ul>
            </div>
            """

        vpn_html_content = f"""
        <div class="vpn-container">
            <div class="vpn-summary-box">
                <div><strong>Total de túneis:</strong> {vpns_total}</div>
                <div><strong>Online:</strong> {vpns_online}</div>
                <div><strong>Offline:</strong> {vpns_offline}</div>
                <div><strong>Regionais com VPN offline:</strong> {len(regionais_offline_exibicao)}</div>
            </div>
            <div id="vpn-regionais-summary" class="vpn-regionals-grid">
                {resumo_regionais_html}
            </div>
            {regionais_offline_html}
            <div id="vpn-tunels-grid" class="vpn-tunels-grid">
                {cards_tuneis_html}
            </div>
        </div>
        """

except Exception as e:
    # Caso falhe a conexão com o Fortigate ao gerar o dash
    vpns_online = 0
    vpns_offline = 0
    vpn_regionais_total = 0
    vpn_regionais_com_offline = 0
    vpn_regionais_sem_offline = 0
    vpn_html_content = f"<div class='error-container'>Erro ao consultar Fortigate: {str(e)}</div>"
# --- FIM DA LÓGICA DE VPN ---

# === 10. MONTA DASHBOARD FINAL ===
# Construct the final HTML dashboard using f-strings for dynamic content insertion.
dashboard_html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard Consolidado</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <!-- Font Awesome for icons -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
        
        :root {{
            --primary-gradient: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            --secondary-gradient: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            --success-gradient: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            --warning-gradient: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);
            --error-gradient: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
            --neutral-gradient: linear-gradient(135deg, #a8edea 0%, #fed6e3 100%);
            --glass-bg: rgba(255, 255, 255, 0.25);
            --glass-border: rgba(255, 255, 255, 0.18);
            --shadow-soft: 0 8px 32px 0 rgba(31, 38, 135, 0.37);
            --shadow-hover: 0 15px 35px rgba(31, 38, 135, 0.2);
        }}
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 50%, #f093fb 100%);
            background-attachment: fixed;
            color: #2d3748;
            line-height: 1.6;
            min-height: 100vh;
        }}
        
        .main-container {{
            backdrop-filter: blur(10px);
            background: var(--glass-bg);
            border: 1px solid var(--glass-border);
            border-radius: 20px;
            margin: 20px;
            padding: 40px;
            box-shadow: var(--shadow-soft);
        }}
        
        .page-title {{
            color: #ffffff;
            font-size: 3.5rem;
            font-weight: 800;
            text-align: center;
            margin-bottom: 10px;
            letter-spacing: -0.02em;
        }}
        
        .page-subtitle {{
            text-align: center;
            color: rgba(45, 55, 72, 0.8);
            font-size: 1.1rem;
            font-weight: 500;
            margin-bottom: 40px;
        }}
        
        .kpi-container {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
            align-items: stretch;
        }}
        
        .kpi {{
            background: rgba(255, 255, 255, 0.9);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 16px;
            padding: 24px;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}
        
        .kpi::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 4px;
            background: var(--primary-gradient);
            border-radius: 16px 16px 0 0;
        }}
        
        .kpi:hover {{
            transform: translateY(-8px);
            box-shadow: var(--shadow-hover);
            background: rgba(255, 255, 255, 0.95);
        }}
        
        .kpi-header {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 16px;
        }}
        
        .kpi-icon {{
            width: 40px;
            height: 40px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 18px;
            color: white;
        }}
        
        .kpi-icon.success {{ background: var(--success-gradient); }}
        .kpi-icon.error {{ background: var(--error-gradient); }}
        .kpi-icon.warning {{ background: var(--warning-gradient); }}
        .kpi-icon.info {{ background: var(--primary-gradient); }}
        .kpi-icon.neutral {{ background: var(--neutral-gradient); }}
        
        .kpi-header h3 {{
            font-size: 0.9rem;
            font-weight: 600;
            color: #4a5568;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            line-height: 1.25;
            overflow-wrap: normal;
            word-break: keep-all;
            hyphens: none;
        }}
        
        .kpi-value {{
            font-size: 2.5rem;
            font-weight: 700;
            color: #2d3748;
            margin-bottom: 8px;
            line-height: 1.05;
        }}
        
        .kpi-status {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.9rem;
            font-weight: 500;
            flex-wrap: wrap;
        }}
        
        .kpi ul {{
            font-size: 0.85rem;
            margin-top: 12px;
            padding-left: 20px;
            color: #e53e3e;
        }}

        .kpi-combo-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
            margin-top: 6px;
        }}

        .kpi-combo-item {{
            background: rgba(255, 255, 255, 0.86);
            border: 1px solid #dbe3f2;
            border-radius: 10px;
            padding: 8px 10px;
            display: grid;
            gap: 2px;
        }}

        .kpi-combo-item.status-online {{
            background: #f0fff4;
            border-color: #9ae6b4;
        }}

        .kpi-combo-item.status-offline {{
            background: #fff5f5;
            border-color: #feb2b2;
        }}

        .kpi-combo-item.status-neutral {{
            background: #f8fafc;
            border-color: #cbd5e0;
        }}

        .kpi-combo-item span {{
            font-size: 0.72rem;
            color: #4a5568;
            text-transform: none;
            letter-spacing: 0.01em;
            font-weight: 700;
            line-height: 1.2;
            overflow-wrap: normal;
            word-break: keep-all;
            hyphens: none;
            white-space: normal;
            overflow: visible;
            text-overflow: clip;
        }}

        .kpi-groups {{
            display: grid;
            gap: 10px;
        }}

        .kpi-group {{
            border: 1px solid #dbe3f2;
            border-radius: 12px;
            padding: 10px;
            background: rgba(255, 255, 255, 0.72);
        }}

        .kpi-group-title {{
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            font-weight: 800;
            color: #4a5568;
            margin-bottom: 8px;
        }}

        .kpi-group-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 8px;
        }}

        .kpi-combo-item strong {{
            font-size: 1.15rem;
            line-height: 1.1;
            color: #1f2937;
        }}

        .regionais-parent {{
            background: linear-gradient(135deg, rgba(240, 255, 244, 0.95) 0%, rgba(255, 255, 255, 0.92) 100%);
            border: 1px solid #9ae6b4;
            border-left: 8px solid #38a169;
            border-radius: 16px;
            padding: 20px 24px;
            margin-bottom: 22px;
            box-shadow: 0 12px 30px rgba(15, 23, 42, 0.1);
        }}

        .regionais-parent-top {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 16px;
            flex-wrap: wrap;
        }}

        .regionais-parent-title {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}

        .regionais-parent-badge {{
            background: linear-gradient(135deg, #e6fffa 0%, #d9fbe9 100%);
            border: 1px solid #9ae6b4;
            color: #1f6f43;
            border-radius: 12px;
            padding: 10px 14px;
            font-size: 1.05rem;
            font-weight: 800;
            letter-spacing: 0.02em;
            white-space: nowrap;
        }}

        .vm-item .card {{
            border: 1px solid rgba(255, 255, 255, 0.22);
            border-radius: 16px;
            overflow: hidden;
            background: rgba(255, 255, 255, 0.96);
            box-shadow: 0 12px 28px rgba(15, 23, 42, 0.08);
        }}

        .vm-item .card-header {{
            padding: 14px 18px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            color: #ffffff;
        }}

        .vm-item .card-header.bg-success {{
            background: linear-gradient(90deg, #2f855a, #38a169);
        }}

        .vm-item .card-header.bg-danger {{
            background: linear-gradient(90deg, #c53030, #e53e3e);
        }}

        .vm-item .card-header h4 {{
            margin: 0;
            font-size: 1.05rem;
            font-weight: 800;
            color: #ffffff;
        }}

        .vm-item .card-header small {{
            color: rgba(255, 255, 255, 0.9);
        }}

        .vm-item .card-body {{
            padding: 18px 20px;
            color: #2d3748;
        }}

        .vm-item .card-body h6 {{
            margin-bottom: 10px;
            color: #1f2937;
            font-weight: 700;
        }}

        .vm-item .card-body p {{
            margin-bottom: 8px;
        }}

        .regionais-parent h2 {{
            margin: 0;
            padding: 0;
            font-size: 1.05rem;
            color: #1f6f43 !important;
            background: none !important;
            font-weight: 800;
            letter-spacing: 0.03em;
            border-radius: 0;
            cursor: default;
        }}

        .regionais-parent p {{
            margin: 8px 0 0;
            color: #4a5568;
            font-size: 0.95rem;
        }}
        
        .charts-section {{
            margin: 50px 0;
        }}
        
        .section-title {{
            font-size: 2.2rem;
            font-weight: 700;
            text-align: center;
            margin-bottom: 30px;
            color: #ffffff;
        }}
        
        .charts-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 30px;
        }}
        
        .chart-wrapper {{
            background: rgba(255, 255, 255, 0.9);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 20px;
            padding: 30px;
            box-shadow: var(--shadow-soft);
            transition: all 0.3s ease;
            min-height: 350px;
            display: flex;
            justify-content: center;
            align-items: center;
        }}
        
        .chart-wrapper:hover {{
            transform: translateY(-5px);
            box-shadow: var(--shadow-hover);
        }}
        
        .divider {{
            height: 2px;
            background: var(--primary-gradient);
            border: none;
            border-radius: 2px;
            margin: 50px 0;
            opacity: 0.3;
        }}
        
        .details-section {{
            background: rgba(255, 255, 255, 0.9);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 16px;
            margin-bottom: 20px;
            overflow: hidden;
            box-shadow: var(--shadow-soft);
            transition: all 0.3s ease;
        }}
        
        .details-section:hover {{
            box-shadow: var(--shadow-hover);
        }}
        
        .details-section summary {{
            background: rgba(255, 255, 255, 0.1);
            padding: 20px 30px;
            cursor: pointer;
            font-size: 1.3rem;
            font-weight: 600;
            color: #2d3748;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            transition: all 0.3s ease;
            position: relative;
        }}

        .section-close-btn {{
            position: absolute;
            right: 12px;
            top: 50%;
            transform: translateY(-50%);
            width: 32px;
            height: 32px;
            border: 1px solid #cbd5e0;
            border-radius: 999px;
            background: #ffffff;
            color: #4a5568;
            font-size: 1.1rem;
            font-weight: 700;
            line-height: 1;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 2;
        }}

        .section-close-btn:hover {{
            background: #f7fafc;
            color: #2d3748;
        }}

        /* Floating back-to-top button */
        .back-to-top {{
            position: fixed;
            bottom: 32px;
            right: 32px;
            z-index: 9999;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #ffffff;
            border: none;
            border-radius: 50%;
            width: 52px;
            height: 52px;
            font-size: 1.6rem;
            cursor: pointer;
            box-shadow: 0 4px 18px rgba(102,126,234,0.45);
            display: flex;
            align-items: center;
            justify-content: center;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.3s, transform 0.3s;
        }}
        .back-to-top.visible {{
            opacity: 1;
            pointer-events: auto;
        }}
        .back-to-top:hover {{
            transform: translateY(-4px);
            box-shadow: 0 8px 24px rgba(102,126,234,0.6);
        }}
        
        .details-section summary:hover {{
            background: rgba(255, 255, 255, 0.2);
        }}
        
        .details-section summary::marker {{
            display: none;
        }}
        
        .details-section summary::before {{
            content: '';
            position: absolute;
            right: 30px;
            top: 50%;
            transform: translateY(-50%);
            transition: transform 0.3s ease;
            color: #667eea;
            font-size: 1.2rem;
        }}
        
        .details-section[open] summary::before {{
            transform: translateY(-50%) rotate(90deg);
        }}
        
        .details-content {{
            padding: 30px;
            background: rgba(255, 255, 255, 0.05);
        }}

        .switches-container {{
            display: grid;
            gap: 18px;
        }}

        .switches-summary,
        .switches-regionals-panel {{
            background: rgba(255, 255, 255, 0.18);
            border: 1px solid rgba(255, 255, 255, 0.28);
            border-radius: 16px;
            padding: 22px;
            box-shadow: 0 14px 40px rgba(15, 23, 42, 0.08);
        }}

        .switches-metrics {{
            display: grid;
            gap: 12px;
        }}

        .switches-regionals {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 12px;
            margin-top: 14px;
        }}

        .regional-badge {{
            background: #ffffff;
            border: 1px solid #d2d6dc;
            border-radius: 14px;
            padding: 14px 16px;
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
            color: #2d3748;
            line-height: 1.45;
        }}

        .regional-badge-success {{
            border-left: 6px solid #2f855a;
            background: #f0fff4;
        }}

        .regional-badge-danger {{
            border-left: 6px solid #c53030;
            background: #fff5f5;
        }}

        .switches-items {{
            display: grid;
            gap: 16px;
        }}

        .switch-item .card {{
            border: 1px solid rgba(255, 255, 255, 0.22);
            border-radius: 16px;
            overflow: hidden;
            background: rgba(255, 255, 255, 0.94);
            box-shadow: 0 20px 45px rgba(15, 23, 42, 0.08);
        }}

        .switch-item .card-header {{
            padding: 16px 20px;
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 12px;
            background: linear-gradient(90deg, rgba(255,255,255,0.96), rgba(255,255,255,0.88));
        }}

        .switch-item .card-header h5 {{
            margin: 0;
            font-size: 1rem;
        }}

        .switch-item .card-header small {{
            color: #4a5568;
            display: block;
            margin-top: 4px;
        }}

        .switch-item .card-body {{
            padding: 20px;
            color: #2d3748;
        }}

        .status-badge {{
            padding: 7px 14px;
            border-radius: 999px;
            color: #ffffff;
            font-size: 0.78rem;
            font-weight: 700;
            text-transform: uppercase;
        }}

        .status-badge.success {{ background: #38a169; }}
        .status-badge.danger {{ background: #e53e3e; }}
        .status-badge.warning {{ background: #dd6b20; }}

        .regional-item {{
            background: rgba(255, 255, 255, 0.8);
            border: 1px solid rgba(255, 255, 255, 0.3);
            border-radius: 12px;
            margin-bottom: 16px;
            overflow: hidden;
            box-shadow: 0 4px 16px rgba(31, 38, 135, 0.15);
        }}
        
        .regional-item summary {{
            background: rgba(255, 255, 255, 0.1);
            padding: 16px 20px;
            font-weight: 600;
            color: #4a5568;
        }}
        
        .regional-content {{
            padding: 20px;
            background: rgba(255, 255, 255, 0.9);
        }}

        #replicacao table th {{
            color: #000 !important;
            background-color: #dbeafe !important;
            font-weight: 700;
        }}

        #replicacao table td {{
            color: #1f2937 !important;
        }}
        
        .error-container {{
            background: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
            color: white;
            padding: 20px;
            border-radius: 12px;
            text-align: center;
            box-shadow: 0 4px 16px rgba(250, 112, 154, 0.3);
            margin: 10px 0;
        }}
        
        .error-icon {{
            font-size: 2rem;
            margin-bottom: 10px;
        }}
        
        .error-title {{
            font-size: 1.2rem;
            font-weight: 600;
            margin-bottom: 8px;
        }}
        
        .error-message {{
            font-size: 0.9rem;
            opacity: 0.9;
        }}

        .nav-detail-trigger {{
            cursor: pointer;
        }}
        
        /* Responsive adjustments */
        @media (max-width: 768px) {{
            .main-container {{
                margin: 10px;
                padding: 20px;
            }}
            
            .page-title {{
                font-size: 2.5rem;
            }}
            
            .kpi-container {{
                grid-template-columns: 1fr;
            }}
            
            .charts-grid {{
                grid-template-columns: 1fr;
            }}
        }}

        .links-container {{
            display: grid;
            gap: 18px;
        }}

        .links-overview {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 12px;
        }}

        .regional-chip {{
            background: rgba(255, 255, 255, 0.92);
            border: 1px solid #d2d6dc;
            border-left: 6px solid #718096;
            border-radius: 14px;
            padding: 14px 16px;
            box-shadow: 0 8px 20px rgba(15, 23, 42, 0.08);
            color: #2d3748;
        }}

        .regional-chip.sp {{ border-left-color: #3182ce; }}
        .regional-chip.rj {{ border-left-color: #dd6b20; }}
        .regional-chip.other {{ border-left-color: #4a5568; }}

        .regional-chip-header {{
            font-size: 0.95rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}

        .regional-chip-stats {{
            margin-top: 8px;
            font-weight: 600;
        }}

        .regional-chip-stats .ok,
        .links-region-counts .ok {{ color: #2f855a; }}

        .regional-chip-stats .alert,
        .links-region-counts .alert {{ color: #c53030; }}

        .regional-chip-stats .sep {{
            margin: 0 6px;
            color: #718096;
        }}

        .links-regions-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 16px;
        }}

        .links-region-block {{
            background: rgba(255, 255, 255, 0.82);
            border: 1px solid rgba(255, 255, 255, 0.3);
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 16px 30px rgba(15, 23, 42, 0.08);
        }}

        .links-region-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            padding: 14px 18px;
            background: linear-gradient(90deg, rgba(247, 250, 252, 0.95), rgba(237, 242, 247, 0.92));
            border-bottom: 1px solid #dfe6ef;
            color: #1a202c;
        }}

        .links-region-header h4 {{
            margin: 0;
            font-size: 1.1rem;
            font-weight: 800;
            letter-spacing: 0.03em;
        }}

        .links-region-counts {{
            display: flex;
            gap: 10px;
            font-size: 0.88rem;
            font-weight: 700;
        }}

        .links-region-items {{
            display: grid;
            gap: 12px;
            padding: 14px;
        }}

        .link-item .card {{
            border: 1px solid #d9e2ec;
            border-radius: 14px;
            overflow: hidden;
            box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06);
        }}

        .link-item .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            padding: 12px 14px;
        }}

        .link-item .card-header h5 {{
            color: #000 !important;
            font-size: 1rem;
        }}

        .link-item .card-header small {{
            color: #1a202c !important;
            opacity: 0.85;
        }}

        .status-pill {{
            border-radius: 999px;
            padding: 6px 12px;
            font-size: 0.75rem;
            font-weight: 700;
            text-transform: uppercase;
            color: #ffffff;
            white-space: nowrap;
        }}

        .status-pill.success {{ background: #2f855a; }}
        .status-pill.danger {{ background: #c53030; }}

        .link-item .card-body {{
            padding: 14px 16px;
        }}

        .link-item .card-body,
        .link-item .card-body p,
        .link-item .card-body strong {{
            color: #000 !important;
        }}

        .link-meta-grid,
        .link-bandwidth-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(120px, 1fr));
            gap: 8px 14px;
        }}

        .link-last-check {{
            margin-top: 10px;
            font-size: 0.9rem;
            color: #1a202c !important;
        }}

        .link-monitor {{
            margin-bottom: 8px;
            color: #1a202c !important;
            font-size: 0.9rem;
        }}

        .link-monitor-note {{
            color: #4a5568;
            font-size: 0.82rem;
        }}

        .vpn-container {{
            display: grid;
            gap: 14px;
        }}

        .vpn-summary-box {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 10px;
            background: rgba(255, 255, 255, 0.9);
            border: 1px solid #dbe3f2;
            border-radius: 14px;
            padding: 14px 16px;
            color: #1f2937;
        }}

        .vpn-regionals-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 10px;
        }}

        .vpn-regional-badge {{
            background: #ffffff;
            border: 1px solid #d5dfef;
            border-left: 5px solid #3b82f6;
            border-radius: 12px;
            padding: 10px 12px;
            box-shadow: 0 8px 18px rgba(15, 23, 42, 0.06);
            color: #1f2937;
        }}

        .vpn-regional-badge .ok {{ color: #2f855a; }}
        .vpn-regional-badge .alert {{ color: #c53030; }}
        .vpn-regional-badge.vpn-regional-alert {{ border-left-color: #dd6b20; }}

        .vpn-offline-box {{
            background: #fff7ed;
            border: 1px solid #fbd38d;
            border-left: 6px solid #dd6b20;
            border-radius: 12px;
            padding: 12px 14px;
            color: #7b341e;
        }}

        .vpn-offline-box ul {{
            margin: 8px 0 0 18px;
        }}

        .vpn-tunels-grid {{
            display: grid;
            gap: 12px;
        }}

        .vpn-regional-group {{
            background: rgba(255, 255, 255, 0.92);
            border: 1px solid #dbe3f2;
            border-radius: 12px;
            padding: 12px;
            display: grid;
            gap: 8px;
        }}

        .vpn-regional-group h4 {{
            margin: 0 0 4px;
            font-size: 1rem;
            color: #1e293b;
        }}

        .vpn-tunnel-card {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 10px;
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            padding: 10px 12px;
            color: #1f2937;
        }}

        .vpn-status-pill {{
            border-radius: 999px;
            padding: 5px 10px;
            color: #fff;
            font-size: 0.74rem;
            font-weight: 700;
        }}

        .vpn-status-pill.online {{ background: #2f855a; }}
        .vpn-status-pill.offline {{ background: #c53030; }}

        @media (max-width: 640px) {{
            .link-meta-grid,
            .link-bandwidth-grid {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="main-container">
        <h1 class="page-title">Dashboard Consolidado</h1>
        <p class="page-subtitle"><strong>Executado em:</strong> {data_execucao}</p>

        <div class="regionais-parent nav-detail-trigger" data-detail-target="regionais" role="button" tabindex="0">
            <div class="regionais-parent-top">
                <div class="regionais-parent-title">
                    <h2 style="background:none!important;color:#1f6f43!important;padding:0!important;border-radius:0!important;cursor:default!important"><strong>Base de Monitoramento: Regionais</strong></h2>
                </div>
                <div class="regionais-parent-badge">{total_regionais_cadastradas} regionais monitoradas</div>
            </div>
            <p>Este painel mostra, de forma simples, a situação das regionais: antenas, switches, servidores e links.</p>
        </div>

        <div class="kpi-container">
            <div class="kpi nav-detail-trigger" data-detail-target="regionais" role="button" tabindex="0">
                <div class="kpi-header">
                    <div class="kpi-icon error">
                        <i class="fas fa-times-circle"></i>
                    </div>
                    <h3>Regionais com Problema no Servidor</h3>
                </div>
                <div class="kpi-groups">
                    <div class="kpi-group">
                        <div class="kpi-group-title">Servidores</div>
                        <div class="kpi-group-grid">
                            <div class="kpi-combo-item status-online nav-detail-trigger" data-detail-target="regionais-online" role="button" tabindex="0"><span>Online</span><strong>{servidores_online_total}</strong></div>
                            <div class="kpi-combo-item status-offline nav-detail-trigger" data-detail-target="regionais-offline" role="button" tabindex="0"><span>Offline</span><strong>{servidores_offline_total}</strong></div>
                        </div>
                    </div>
                    <div class="kpi-group">
                        <div class="kpi-group-title">Regionais</div>
                        <div class="kpi-group-grid">
                            <div class="kpi-combo-item status-online nav-detail-trigger" data-detail-target="regionais-online" role="button" tabindex="0"><span>Sem offline</span><strong>{regionais_servidor_sem_offline}</strong></div>
                            <div class="kpi-combo-item status-offline nav-detail-trigger" data-detail-target="regionais-offline" role="button" tabindex="0"><span>Com offline</span><strong>{regionais_servidor_com_offline}</strong></div>
                        </div>
                    </div>
                </div>
            </div>
            <div class="kpi nav-detail-trigger" data-detail-target="unifi" role="button" tabindex="0">
                <div class="kpi-header">
                    <div class="kpi-icon info">
                        <i class="fas fa-wifi"></i>
                    </div>
                    <h3>APs (Regionais)</h3>
                </div>
                <div class="kpi-groups">
                    <div class="kpi-group">
                        <div class="kpi-group-title">Dispositivos</div>
                        <div class="kpi-group-grid">
                            <div class="kpi-combo-item status-online nav-detail-trigger" data-detail-target="unifi-online" role="button" tabindex="0"><span>APs Online</span><strong>{aps_online}</strong></div>
                            <div class="kpi-combo-item status-offline nav-detail-trigger" data-detail-target="unifi-offline" role="button" tabindex="0"><span>APs Offline</span><strong>{aps_offline}</strong></div>
                        </div>
                    </div>
                    <div class="kpi-group">
                        <div class="kpi-group-title">Regionais</div>
                        <div class="kpi-group-grid">
                            <div class="kpi-combo-item status-online nav-detail-trigger" data-detail-target="unifi-online" role="button" tabindex="0"><span>Sem AP Offline</span><strong>{aps_regionais_sem_offline}</strong></div>
                            <div class="kpi-combo-item status-offline nav-detail-trigger" data-detail-target="unifi-offline" role="button" tabindex="0"><span>Com AP Offline</span><strong>{aps_regionais_com_offline}</strong></div>
                        </div>
                    </div>
                </div>
            </div>
            <div class="kpi nav-detail-trigger" data-detail-target="gps" role="button" tabindex="0">
                <div class="kpi-header">
                    <div class="kpi-icon warning">
                        <i class="fas fa-camera"></i>
                    </div>
                    <h3>Prints GPS</h3>
                </div>
                <div class="kpi-combo-grid">
                    <div class="kpi-combo-item {'status-online' if gps_amigo_ok else 'status-offline'} nav-detail-trigger" data-detail-target="gps" role="button" tabindex="0"><span>GPS Amigo</span><strong>{'OK' if gps_amigo_ok else 'Falha'}</strong></div>
                    <div class="kpi-combo-item {'status-online' if print_rede_ok else 'status-offline'} nav-detail-trigger" data-detail-target="print-rede" role="button" tabindex="0"><span>Rede Saturno</span><strong>{'OK' if print_rede_ok else 'Falha'}</strong></div>
                    <div class="kpi-combo-item {'status-online' if print_firewall_ok else 'status-offline'} nav-detail-trigger" data-detail-target="appgate" role="button" tabindex="0"><span>Firewall RJ</span><strong>{'OK' if print_firewall_ok else 'Falha'}</strong></div>
                </div>
            </div>
            <div class="kpi nav-detail-trigger" data-detail-target="replicacao" role="button" tabindex="0">
                <div class="kpi-header">
                    <div class="kpi-icon info">
                        <i class="fas fa-sync-alt"></i>
                    </div>
                    <h3>Replicação AD</h3>
                </div>
                <div class="kpi-groups">
                    <div class="kpi-group">
                        <div class="kpi-group-title">Dispositivos</div>
                        <div class="kpi-group-grid">
                            <div class="kpi-combo-item status-online nav-detail-trigger" data-detail-target="replicacao" role="button" tabindex="0"><span>Servidores OK</span><strong>{rep_ok}</strong></div>
                            <div class="kpi-combo-item status-offline nav-detail-trigger" data-detail-target="replicacao" role="button" tabindex="0"><span>Com falha</span><strong>{rep_fail}</strong></div>
                            <div class="kpi-combo-item status-neutral nav-detail-trigger" data-detail-target="replicacao" role="button" tabindex="0"><span>Total</span><strong>{rep_total}</strong></div>
                            <div class="kpi-combo-item {'status-online' if rep_fail == 0 else 'status-offline'} nav-detail-trigger" data-detail-target="replicacao" role="button" tabindex="0"><span>Sem falha</span><strong>{rep_ok}</strong></div>
                        </div>
                    </div>
                </div>
                {"<ul>" + ''.join(f"<li>{srv}</li>" for srv in replication_errors_list) + "</ul>" if replication_errors_list else ""}
            </div>
            <div class="kpi nav-detail-trigger" data-detail-target="vms" role="button" tabindex="0">
                <div class="kpi-header">
                    <div class="kpi-icon success">
                        <i class="fas fa-desktop"></i>
                    </div>
                    <h3>VMs (Regionais)</h3>
                </div>
                <div class="kpi-groups">
                    <div class="kpi-group">
                        <div class="kpi-group-title">Dispositivos</div>
                        <div class="kpi-group-grid">
                            <div class="kpi-combo-item status-online nav-detail-trigger" data-detail-target="vms-online" role="button" tabindex="0"><span>VMs online</span><strong>{vms_online}</strong></div>
                            <div class="kpi-combo-item status-offline nav-detail-trigger" data-detail-target="vms-offline" role="button" tabindex="0"><span>VMs offline</span><strong>{vms_offline}</strong></div>
                        </div>
                    </div>
                    <div class="kpi-group">
                        <div class="kpi-group-title">Regionais</div>
                        <div class="kpi-group-grid">
                            <div class="kpi-combo-item status-online nav-detail-trigger" data-detail-target="vms-online" role="button" tabindex="0"><span>Sem offline</span><strong>{vms_regionais_sem_offline}</strong></div>
                            <div class="kpi-combo-item status-offline nav-detail-trigger" data-detail-target="vms-offline" role="button" tabindex="0"><span>Com offline</span><strong>{vms_regionais_com_offline}</strong></div>
                        </div>
                    </div>
                </div>
            </div>
            <div class="kpi nav-detail-trigger" data-detail-target="switches" role="button" tabindex="0">
                <div class="kpi-header">
                    <div class="kpi-icon success">
                        <i class="fas fa-network-wired"></i>
                    </div>
                    <h3>Switches (Regionais)</h3>
                </div>
                <div class="kpi-groups">
                    <div class="kpi-group">
                        <div class="kpi-group-title">Dispositivos</div>
                        <div class="kpi-group-grid">
                            <div class="kpi-combo-item status-online nav-detail-trigger" data-detail-target="switches-online" role="button" tabindex="0"><span>Switches Online</span><strong>{switches_online}</strong></div>
                            <div class="kpi-combo-item status-offline nav-detail-trigger" data-detail-target="switches-offline" role="button" tabindex="0"><span>Switches Offline</span><strong>{switches_offline}</strong></div>
                        </div>
                    </div>
                    <div class="kpi-group">
                        <div class="kpi-group-title">Regionais</div>
                        <div class="kpi-group-grid">
                            <div class="kpi-combo-item status-online nav-detail-trigger" data-detail-target="switches-online" role="button" tabindex="0"><span>Sem Switch Offline</span><strong>{switches_regionais_sem_offline}</strong></div>
                            <div class="kpi-combo-item status-offline nav-detail-trigger" data-detail-target="switches-offline" role="button" tabindex="0"><span>Com Switch Offline</span><strong>{switches_regionais_com_offline}</strong></div>
                        </div>
                    </div>
                </div>
            </div>
            <div class="kpi nav-detail-trigger" data-detail-target="links" role="button" tabindex="0">
                <div class="kpi-header">
                    <div class="kpi-icon info">
                        <i class="fas fa-globe"></i>
                    </div>
                    <h3>Links (Regionais)</h3>
                </div>
                <div class="kpi-groups">
                    <div class="kpi-group">
                        <div class="kpi-group-title">Links</div>
                        <div class="kpi-group-grid">
                            <div class="kpi-combo-item status-online nav-detail-trigger" data-detail-target="links-online" role="button" tabindex="0"><span>Online</span><strong>{links_online}</strong></div>
                            <div class="kpi-combo-item status-offline nav-detail-trigger" data-detail-target="links-offline" role="button" tabindex="0"><span>Offline</span><strong>{links_offline}</strong></div>
                        </div>
                    </div>
                    <div class="kpi-group">
                        <div class="kpi-group-title">Cobertura Regional</div>
                        <div class="kpi-group-grid">
                            <div class="kpi-combo-item status-online nav-detail-trigger" data-detail-target="links-online" role="button" tabindex="0"><span>Sem offline</span><strong>{links_regionais_sem_offline}</strong></div>
                            <div class="kpi-combo-item status-offline nav-detail-trigger" data-detail-target="links-offline" role="button" tabindex="0"><span>Com offline</span><strong>{links_regionais_com_offline}</strong></div>
                        </div>
                    </div>
                </div>
            </div>
            <div class="kpi nav-detail-trigger" data-detail-target="vpn-details" role="button" tabindex="0">
                <div class="kpi-header">
                    <div class="kpi-icon info">
                        <i class="fas fa-shield-alt"></i>
                    </div>
                    <h3>VPNs IPSEC</h3>
                </div>
                <div class="kpi-groups">
                    <div class="kpi-group">
                        <div class="kpi-group-title">Dispositivos</div>
                        <div class="kpi-group-grid">
                            <div class="kpi-combo-item status-online nav-detail-trigger" data-detail-target="vpn-details-online" role="button" tabindex="0"><span>Túneis online</span><strong>{vpns_online}</strong></div>
                            <div class="kpi-combo-item status-offline nav-detail-trigger" data-detail-target="vpn-details-offline" role="button" tabindex="0"><span>Túneis offline</span><strong>{vpns_offline}</strong></div>
                        </div>
                    </div>
                    <div class="kpi-group">
                        <div class="kpi-group-title">Regionais</div>
                        <div class="kpi-group-grid">
                            <div class="kpi-combo-item status-online nav-detail-trigger" data-detail-target="vpn-details-online" role="button" tabindex="0"><span>Sem offline</span><strong>{vpn_regionais_sem_offline}</strong></div>
                            <div class="kpi-combo-item status-offline nav-detail-trigger" data-detail-target="vpn-details-offline" role="button" tabindex="0"><span>Com offline</span><strong>{vpn_regionais_com_offline}</strong></div>
                        </div>
                    </div>
                </div>
            </div>
            
        </div>

        <!-- GRÁFICOS -->
        <div class="charts-section">
            <h2 class="section-title" style="background:none!important;color:#ffffff!important;padding:0!important;border-radius:0!important;cursor:default!important">[DATA] Visão Geral em Gráficos</h2>
            <div class="charts-grid">
                <div class="chart-wrapper nav-detail-trigger" data-detail-target="regionais" role="button" tabindex="0">
                    <canvas id="chartRegionais"></canvas>
                </div>
                <div class="chart-wrapper nav-detail-trigger" data-detail-target="unifi" role="button" tabindex="0">
                    <canvas id="chartUnifi"></canvas>
                </div>
                <div class="chart-wrapper nav-detail-trigger" data-detail-target="replicacao" role="button" tabindex="0">
                    <canvas id="chartReplicacao"></canvas>
                </div>
                <div class="chart-wrapper nav-detail-trigger" data-detail-target="vms" role="button" tabindex="0">
                    <canvas id="chartVMs"></canvas>
                </div>
                <div class="chart-wrapper nav-detail-trigger" data-detail-target="switches" role="button" tabindex="0">
                    <canvas id="chartSwitches"></canvas>
                </div>
                <div class="chart-wrapper nav-detail-trigger" data-detail-target="links" role="button" tabindex="0">
                    <canvas id="chartLinks"></canvas>
                </div>
                <div class="chart-wrapper nav-detail-trigger" data-detail-target="vpn-details" role="button" tabindex="0">
                    <canvas id="chartVpn"></canvas>
                </div>
            </div>
        </div>

        <hr class="divider">

        <details id="regionais" class="details-section">
            <summary>[SERVER] Status das Regionais (iDRAC/iLO)</summary>
            <div class="details-content">
                {regionais_html}
            </div>
        </details>

        <details id="gps" class="details-section">
            <summary>[URL] Print GPS Amigo</summary>
            <div class="details-content">
                {gps_html}
            </div>
        </details>

        <details id="print-rede" class="details-section">
            <summary>[URL] Print Rede</summary>
            <div class="details-content">
                {print_rede_html}
            </div>
        </details>

        <details id="appgate" class="details-section">
            <summary>[URL] Print Firewall Rio de Janeiro</summary>
            <div class="details-content">
                {appgate_html}
            </div>
        </details>

        <details id="replicacao" class="details-section">
            <summary>[UPDATE] Status de Replicação do Active Directory</summary>
            <div class="details-content">
                {rep_html}
            </div>
        </details>

        <details id="unifi" class="details-section">
            <summary> Status das Antenas UniFi (por site)</summary>
            <div class="details-content">
                {unifi_html}
            </div>
        </details>

        <details id="vms" class="details-section">
            <summary>[PC] Status das Máquinas Virtuais</summary>
            <div class="details-content">
                {relatorio_vms}
            </div>
        </details>

        <details id="switches" class="details-section">
            <summary> Status dos Switches</summary>
            <div class="details-content">
                {switches_html_content}
            </div>
        </details>

        <details id="links" class="details-section">
            <summary>[WEB] Status dos Links de Internet</summary>
            <div class="details-content">
                {links_html_content}
            </div>
        </details>
        <details id="vpn-details" class="details-section">
            <summary>[FORTIGATE] Status VPNs IPSEC</summary>
            <div class="details-content">
                {vpn_html_content}
            </div>
        </details>
    </div>

<script>
// Global configuration to make charts responsive
Chart.defaults.responsive = true;
Chart.defaults.maintainAspectRatio = false; // Important to allow the container to control the aspect ratio

function resetUnifiSections(detail) {{
    const content = detail.querySelector('.details-content');
    if (!content) return;

    const sectionHeaders = content.querySelectorAll('h2');
    sectionHeaders.forEach((header) => {{
        const next = header.nextElementSibling;
        header.style.display = '';
        if (next) {{
            next.style.display = 'none';
            next.querySelectorAll('tr').forEach((tr) => {{ tr.style.display = ''; }});
        }}
    }});
}}

function filtrarUnifiSections(detail, action) {{
    const content = detail.querySelector('.details-content');
    if (!content) return;

    const sectionHeaders = content.querySelectorAll('h2');
    sectionHeaders.forEach((header) => {{
        const next = header.nextElementSibling;
        if (!next) return;

        const hasOffline = !!next.querySelector('.ap-offline');
        const hasOnline = !!next.querySelector('.ap-online');
        let showSection = true;

        if (action === 'offline') {{
            showSection = hasOffline;
        }} else if (action === 'online') {{
            // "Online" = regional sem AP offline (somente APs online)
            showSection = hasOnline && !hasOffline;
        }}

        header.style.display = showSection ? '' : 'none';
        next.style.display = showSection ? 'block' : 'none';

        if (showSection && action === 'offline') {{
            // Dentro da seção, ocultar linhas que NÃO têm AP offline
            next.querySelectorAll('tr').forEach((tr) => {{
                const isOfflineRow = !!tr.querySelector('.ap-offline');
                tr.style.display = isOfflineRow ? '' : 'none';
            }});
        }} else if (showSection) {{
            next.querySelectorAll('tr').forEach((tr) => {{ tr.style.display = ''; }});
        }}
    }});
}}

function resetSwitchesSection(detail) {{
    detail.querySelectorAll('.switch-item').forEach((item) => {{
        item.style.display = '';
    }});
}}

function resetVmsSection(detail) {{
    detail.querySelectorAll('.vm-item').forEach((item) => {{
        item.style.display = '';
    }});
}}

function resetRegionaisSection(detail) {{
    detail.querySelectorAll('.regional-item').forEach((item) => {{
        item.style.display = '';
    }});
}}

function resetLinksSection(detail) {{
    detail.querySelectorAll('.link-item').forEach((item) => {{
        item.style.display = '';
    }});
}}

function resetVpnSection(detail) {{
    detail.querySelectorAll('.vpn-tunnel-card').forEach((card) => {{
        card.style.display = '';
    }});
}}

function resetSectionFilters(detail) {{
    if (!detail) return;
    if (detail.id === 'regionais') resetRegionaisSection(detail);
    if (detail.id === 'unifi') resetUnifiSections(detail);
    if (detail.id === 'switches') resetSwitchesSection(detail);
    if (detail.id === 'vms') resetVmsSection(detail);
    if (detail.id === 'links') resetLinksSection(detail);
    if (detail.id === 'vpn-details') resetVpnSection(detail);
}}

function abrirEIrParaDetalhe(detailTarget) {{
    const parts = String(detailTarget || '').split('-');
    let detailId = detailTarget;
    let action = '';

    // Suporta IDs com hífen (ex.: vpn-details) + ação opcional (ex.: vpn-details-offline)
    for (let i = parts.length; i >= 1; i--) {{
        const candidate = parts.slice(0, i).join('-');
        if (document.getElementById(candidate)) {{
            detailId = candidate;
            action = parts.slice(i).join('-');
            break;
        }}
    }}

    const detail = document.getElementById(detailId);
    if (!detail) {{
        return;
    }}

    detail.open = true;

    if (detailId === 'regionais') {{
        const regionalItems = detail.querySelectorAll('.regional-item');
        if (action === 'offline' || action === 'online') {{
            regionalItems.forEach((item) => {{
                const match = item.dataset.status === action;
                item.style.display = match ? '' : 'none';
                item.open = match;
            }});
        }} else {{
            resetRegionaisSection(detail);
        }}
    }}

    if (detailId === 'unifi') {{
        if (action === 'offline' || action === 'online') {{
            filtrarUnifiSections(detail, action);
        }} else {{
            resetUnifiSections(detail);
        }}
    }}

    if (detailId === 'switches') {{
        const switchItems = detail.querySelectorAll('.switch-item');
        if (action === 'offline' || action === 'online') {{
            switchItems.forEach((item) => {{
                item.style.display = item.dataset.status === action ? '' : 'none';
            }});
        }} else {{
            resetSwitchesSection(detail);
        }}

        if (action === 'offline') {{
            const offlinePanel = detail.querySelector('#switches-offline-regionais');
            if (offlinePanel) {{
                offlinePanel.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
            }}
        }}
    }}

    if (detailId === 'vms') {{
        const vmItems = detail.querySelectorAll('.vm-item');
        if (action === 'offline' || action === 'online') {{
            vmItems.forEach((item) => {{
                item.style.display = item.dataset.status === action ? '' : 'none';
            }});
        }} else {{
            resetVmsSection(detail);
        }}
    }}

    if (detailId === 'links') {{
        const linkItems = detail.querySelectorAll('.link-item');
        if (action === 'offline' || action === 'online') {{
            linkItems.forEach((item) => {{
                item.style.display = item.dataset.status === action ? '' : 'none';
            }});
        }} else {{
            resetLinksSection(detail);
        }}
    }}

    if (detailId === 'vpn-details') {{
        const tunnelCards = detail.querySelectorAll('.vpn-tunnel-card');
        if (action === 'offline' || action === 'online') {{
            tunnelCards.forEach((card) => {{
                card.style.display = card.dataset.status === action ? '' : 'none';
            }});
        }} else {{
            resetVpnSection(detail);
        }}

        if (action === 'offline') {{
            const offlineVpnBox = detail.querySelector('#vpn-offline-regionais');
            if (offlineVpnBox) {{
                offlineVpnBox.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
            }}
        }}
    }}

    setTimeout(function() {{
        detail.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
    }}, 80);
}}

function navegarPeloGrafico(chartId, datasetIndex) {{
    const rotas = {{
        chartRegionais: ['regionais-online', 'regionais-offline'],
        chartUnifi: ['unifi-online', 'unifi-offline'],
        chartReplicacao: ['replicacao', 'replicacao'],
        chartVMs: ['vms-online', 'vms-offline'],
        chartSwitches: ['switches-online', 'switches-offline'],
        chartLinks: ['links-online', 'links-offline'],
        chartVpn: ['vpn-details-online', 'vpn-details-offline'],
    }};

    const rota = (rotas[chartId] && rotas[chartId][datasetIndex]) || null;
    if (rota) {{
        abrirEIrParaDetalhe(rota);
    }}
}}

document.querySelectorAll('[data-detail-target]').forEach((elemento) => {{
    const navegar = (event) => {{
        if (event) event.stopPropagation();
        abrirEIrParaDetalhe(elemento.dataset.detailTarget);
    }};
    elemento.addEventListener('click', navegar);
    elemento.addEventListener('keydown', (event) => {{
        if (event.key === 'Enter' || event.key === ' ') {{
            event.preventDefault();
            navegar(event);
        }}
    }});
}});

document.querySelectorAll('details.details-section').forEach((detail) => {{
    const summary = detail.querySelector('summary');
    if (!summary || summary.querySelector('.section-close-btn')) return;

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'section-close-btn';
    closeBtn.title = 'Fechar seção';
    closeBtn.textContent = '×';
    closeBtn.addEventListener('click', (event) => {{
        event.preventDefault();
        event.stopPropagation();
        // Fecha TODAS as seções e rola para o topo
        document.querySelectorAll('details.details-section').forEach((d) => {{
            d.open = false;
            resetSectionFilters(d);
        }});
        document.querySelectorAll('.regional-item').forEach((item) => {{
            item.open = false;
            item.style.display = '';
        }});
        window.scrollTo({{ top: 0, behavior: 'smooth' }});
    }});
    summary.appendChild(closeBtn);
}});

new Chart(document.getElementById('chartRegionais'), {{
    type: 'doughnut',
    data: {{
        labels: ['Sem Erro em Servidores', 'Com Erro em Servidores'],
        datasets: [{{
            data: [{regionais_sem_erro}, {regionais_erro}],
            backgroundColor: ['#4CAF50', '#F44336'],
            borderColor: '#ffffff',
            borderWidth: 2
        }}]
    }},
    options: {{
        onClick: function(_event, elements) {{
            if (elements && elements.length > 0) {{
                navegarPeloGrafico('chartRegionais', elements[0].index);
            }} else {{
                abrirEIrParaDetalhe('regionais');
            }}
        }},
        plugins: {{
            title: {{
                display: true,
                text: 'Status das Regionais por Servidores',
                font: {{
                    size: 16
                }},
                color: '#333'
            }},
            legend: {{
                position: 'bottom',
                labels: {{
                    font: {{
                        size: 14
                    }},
                    color: '#555'
                }}
            }}
        }}
    }}
}});

new Chart(document.getElementById('chartUnifi'), {{
    type: 'doughnut',
    data: {{
        labels: ['Regionais sem AP offline', 'Regionais com AP offline'],
        datasets: [{{
            data: [{aps_regionais_sem_offline}, {aps_regionais_com_offline}],
            backgroundColor: ['#2196F3', '#B0BEC5'],
            borderColor: '#ffffff',
            borderWidth: 2
        }}]
    }},
    options: {{
        onClick: function(_event, elements) {{
            if (elements && elements.length > 0) {{
                navegarPeloGrafico('chartUnifi', elements[0].index);
            }} else {{
                abrirEIrParaDetalhe('unifi');
            }}
        }},
        plugins: {{
            title: {{
                display: true,
                text: 'APs por Regional',
                font: {{
                    size: 16
                }},
                color: '#333'
            }},
            legend: {{
                position: 'bottom',
                labels: {{
                    font: {{
                        size: 14
                    }},
                    color: '#555'
                }}
            }}
        }}
    }}
}});

new Chart(document.getElementById('chartReplicacao'), {{
    type: 'doughnut',
    data: {{
        labels: ['OK', 'Com Falha'],
        datasets: [{{
            data: [{rep_ok}, {rep_fail}],
            backgroundColor: ['#8BC34A', '#FF7043'],
            borderColor: '#ffffff',
            borderWidth: 2
        }}]
    }},
    options: {{
        onClick: function() {{
            abrirEIrParaDetalhe('replicacao');
        }},
        plugins: {{
            title: {{
                display: true,
                text: 'Replicação AD',
                font: {{
                    size: 16
                }},
                color: '#333'
            }},
            legend: {{
                position: 'bottom',
                labels: {{
                    font: {{
                        size: 14
                    }},
                    color: '#555'
                }}
            }}
        }}
    }}
}});

new Chart(document.getElementById('chartVMs'), {{
    type: 'doughnut',
    data: {{
        labels: ['Online', 'Offline'],
        datasets: [{{
            data: [{vms_online}, {vms_offline}],
            backgroundColor: ['#4CAF50', '#F44336'],
            borderColor: '#ffffff',
            borderWidth: 2
        }}]
    }},
    options: {{
        onClick: function() {{
            abrirEIrParaDetalhe('vms');
        }},
        plugins: {{
            title: {{
                display: true,
                text: 'Status das VMs',
                font: {{
                    size: 16
                }},
                color: '#333'
            }},
            legend: {{
                position: 'bottom',
                labels: {{
                    font: {{
                        size: 14
                    }},
                    color: '#555'
                }}
            }}
        }}
    }}
}});

new Chart(document.getElementById('chartSwitches'), {{
    type: 'doughnut',
    data: {{
        labels: ['Regionais sem switch offline', 'Regionais com switch offline'],
        datasets: [{{
            data: [{switches_regionais_sem_offline}, {switches_regionais_com_offline}],
            backgroundColor: ['#2196F3', '#FF9800'],
            borderColor: '#ffffff',
            borderWidth: 2
        }}]
    }},
    options: {{
        onClick: function(_event, elements) {{
            if (elements && elements.length > 0) {{
                navegarPeloGrafico('chartSwitches', elements[0].index);
            }} else {{
                abrirEIrParaDetalhe('switches');
            }}
        }},
        plugins: {{
            title: {{
                display: true,
                text: 'Switches por Regional',
                font: {{
                    size: 16
                }},
                color: '#333'
            }},
            legend: {{
                position: 'bottom',
                labels: {{
                    font: {{
                        size: 14
                    }},
                    color: '#555'
                }}
            }}
        }}
    }}
}});

new Chart(document.getElementById('chartLinks'), {{
    type: 'doughnut',
    data: {{
        labels: ['Online', 'Offline'],
        datasets: [{{
            data: [{links_online}, {links_offline}],
            backgroundColor: ['#9C27B0', '#E91E63'],
            borderColor: '#ffffff',
            borderWidth: 2
        }}]
    }},
    options: {{
        onClick: function(_event, elements) {{
            if (elements && elements.length > 0) {{
                navegarPeloGrafico('chartLinks', elements[0].index);
            }} else {{
                abrirEIrParaDetalhe('links');
            }}
        }},
        plugins: {{
            title: {{
                display: true,
                text: 'Links de Internet',
                font: {{
                    size: 16
                }},
                color: '#333'
            }},
            legend: {{
                position: 'bottom',
                labels: {{
                    font: {{
                        size: 14
                    }},
                    color: '#555'
                }}
            }}
        }}
    }}
}});

new Chart(document.getElementById('chartVpn'), {{
    type: 'doughnut',
    data: {{
        labels: ['Online', 'Offline'],
        datasets: [{{
            data: [{vpns_online}, {vpns_offline}],
            backgroundColor: ['#4facfe', '#fa709a'],
            borderColor: '#ffffff',
            borderWidth: 2
        }}]
    }},
    options: {{
        onClick: function(_event, elements) {{
            if (elements && elements.length > 0) {{
                navegarPeloGrafico('chartVpn', elements[0].index);
            }} else {{
                abrirEIrParaDetalhe('vpn-details');
            }}
        }},
        plugins: {{
            title: {{
                display: true,
                text: 'Status Túneis VPN',
                font: {{ size: 16 }},
                color: '#333'
            }},
            legend: {{
                position: 'bottom',
                labels: {{ font: {{ size: 14 }}, color: '#555' }}
            }}
        }}
    }}
}});

// Botão flutuante: fechar tudo e voltar ao topo
const backToTopBtn = document.getElementById('backToTopBtn');
window.addEventListener('scroll', () => {{
    if (backToTopBtn) backToTopBtn.classList.toggle('visible', window.scrollY > 300);
}});
if (backToTopBtn) {{
    backToTopBtn.addEventListener('click', () => {{
        document.querySelectorAll('details.details-section').forEach((d) => {{
            d.open = false;
            resetSectionFilters(d);
        }});
        document.querySelectorAll('.regional-item').forEach((item) => {{
            item.open = false;
            item.style.display = '';
        }});
        window.scrollTo({{ top: 0, behavior: 'smooth' }});
    }});
}}
</script>

<button id="backToTopBtn" class="back-to-top" title="Fechar tudo e voltar ao topo">&#8679;</button>

</body>
</html>
"""




# === 10. SALVA O RELATÓRIO ===
# Salva o relatório no novo local (área de trabalho com estrutura de pastas)
DASHBOARD_FINAL.write_text(dashboard_html, encoding="utf-8")
print(f"[OK] Relatório salvo em: {DASHBOARD_FINAL}")

# Também salva no local original para compatibilidade
DASHBOARD_FINAL_ORIGINAL.write_text(dashboard_html, encoding="utf-8")
print(f"[OK] Cópia de compatibilidade salva em: {DASHBOARD_FINAL_ORIGINAL}")



# Exibe informações sobre a estrutura criada
print(f"\n[DIR] Estrutura de Relatório Preventiva:")
print(f"   - Pasta base: {RELATORIO_PREVENTIVA_DIR.parent.parent}")
print(f"   - Ano: {RELATORIO_PREVENTIVA_DIR.parent.parent.name}")
print(f"   - Mês: {RELATORIO_PREVENTIVA_DIR.parent.name}")
print(f"   - Dia: {RELATORIO_PREVENTIVA_DIR.name}")
print(f"   - Arquivo: {DASHBOARD_FINAL.name}")
print(f"\n[TARGET] Acesse o relatório em: {DASHBOARD_FINAL}")

# === 11. REMOVE ARQUIVOS TEMPORÁRIOS ===
# Limpa arquivos HTML temporários gerados durante o processo
for file in REGIONAL_HTMLS_DIR.glob("*.html"):
    file.unlink() # Remove cada arquivo HTML regional
if GPS_HTML.exists():
    GPS_HTML.unlink() # Remove o arquivo HTML do GPS
if REPLICACAO_HTML.exists():
    REPLICACAO_HTML.unlink() # Remove o arquivo HTML do resumo de replicação
if UNIFI_HTML.exists():
    UNIFI_HTML.unlink() # Remove o arquivo HTML dos dados das APs UniFi

# Remove arquivos temporários das novas funcionalidades
vms_temp_file = PROJECT_ROOT / "output" / "relatorio_vms.html"
if vms_temp_file.exists():
    vms_temp_file.unlink() # Remove o arquivo HTML temporário das VMs

# === 12. ABRE NO NAVEGADOR ===
# Abre o arquivo HTML do dashboard gerado no navegador padrão, exceto em modo automático
if AUTO_NO_BROWSER:
    print(f"\n[AUTO] Execução automática concluída. Navegador não será aberto.")
    print(f"[URL] Relatório gerado em: {DASHBOARD_FINAL}")
else:
    print(f"\n[WEB] Abrindo relatório no navegador...")
    print(f"[URL] Local: {DASHBOARD_FINAL}")
    try:
        if sys.platform == "win32":
            os.startfile(str(DASHBOARD_FINAL.resolve()))
        else:
            webbrowser.open(DASHBOARD_FINAL.resolve().as_uri())
    except Exception:
        webbrowser.open(DASHBOARD_FINAL.resolve().as_uri())

print(f"\n[SUCCESS] Relatório Preventiva gerado com sucesso!")
print(f" Localização: {DASHBOARD_FINAL}")
print(f" Data/Hora: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
print(f"[DIR] Estrutura: Desktop/Relatório Preventiva/{RELATORIO_PREVENTIVA_DIR.parent.parent.name}/{RELATORIO_PREVENTIVA_DIR.parent.name}/{RELATORIO_PREVENTIVA_DIR.name}/")
