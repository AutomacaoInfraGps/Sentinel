"""Alpha do atualizador de firmware para switches Aruba Instant On 1830/1930.

O programa e conservador por padrao: sem ``--execute`` ele apenas valida os
argumentos e exibe o plano. Credenciais sao solicitadas por getpass e nunca sao
gravadas pelo programa.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from getpass import getpass
from html.parser import HTMLParser
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import time
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener


SUPPORTED_MODELS = frozenset({"1830", "1930"})
DEFAULT_REBOOT_TIMEOUT = 7 * 60
DEFAULT_TRANSFER_TIMEOUT = 20 * 60
MAX_FIRMWARE_BYTES = 128 * 1024 * 1024
TRANSFER_STATUS_POLL_SECONDS = 60
TRANSFER_CONNECTIVITY_POLL_SECONDS = 10
TRANSFER_CONNECTIVITY_FAILURE_LIMIT = 3
TRANSFER_STALL_TIMEOUT_SECONDS = 5 * 60
__version__ = "0.1.0"

LOGGER = logging.getLogger("att-switches")


class UpdateError(RuntimeError):
    """Erro operacional que pode ser exibido ao usuario sem traceback."""


class UpdateNeedsReview(UpdateError):
    """A transferencia terminou, mas o resultado final nao pode ser confirmado."""


@dataclass(frozen=True)
class WebIdentity:
    url: str
    title: str
    sys_name: str
    sys_descr: str
    model: str | None


@dataclass(frozen=True)
class UpdateAssessment:
    url: str
    host: str
    firmware: Path
    expected_model: str
    expected_version: str
    current_model: str
    current_version: str
    decision: str
    identity: WebIdentity


class LoginPageParser(HTMLParser):
    """Extrai somente metadados publicos da pagina de login do switch."""

    def __init__(self) -> None:
        super().__init__()
        self._inside_title = False
        self._title_parts: list[str] = []
        self.fields: dict[str, str] = {}
        self.element_ids: set[str] = set()

    @property
    def title(self) -> str:
        return "".join(self._title_parts).strip()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value or "" for name, value in attrs}
        if tag.lower() == "title":
            self._inside_title = True
        element_id = attributes.get("id")
        if element_id:
            self.element_ids.add(element_id)
        if tag.lower() == "input":
            key = element_id or attributes.get("name")
            if key:
                self.fields[key] = attributes.get("value", "")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._inside_title = False

    def handle_data(self, data: str) -> None:
        if self._inside_title:
            self._title_parts.append(data)


@dataclass
class ProgressReporter:
    json_output: bool = False
    callback: Callable[[str, int, str], None] | None = None
    last_stage: str = "starting"
    last_percent: int = 0
    failure_stage: str | None = None

    def emit(self, stage: str, percent: int, message: str) -> None:
        percent = max(0, min(100, percent))
        self.last_stage = stage
        self.last_percent = percent
        LOGGER.info("Etapa %s (%s%%): %s", stage, percent, message)
        if self.callback:
            self.callback(stage, percent, message)
        if self.json_output:
            payload = {"stage": stage, "percent": percent, "message": message}
            print(f"PROGRESS_JSON={json.dumps(payload, ensure_ascii=False)}", flush=True)

    def fail(self, message: str) -> None:
        self.failure_stage = self.last_stage
        self.emit("failed", self.last_percent, message)

def concise_exception_message(exc: Exception) -> str:
    if isinstance(exc, UpdateError):
        return str(exc)
    raw = getattr(exc, "msg", None) or str(exc) or exc.__class__.__name__
    first_line = next((line.strip() for line in raw.splitlines() if line.strip()), exc.__class__.__name__)
    return f"Falha do navegador ({exc.__class__.__name__}): {first_line}"[:500]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Alpha para atualizacao de Aruba Instant On 1830/1930."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--url", required=True, help="URL do switch (http://IP ou https://IP).")
    parser.add_argument("--username", required=True, help="Usuario da interface web do switch.")
    parser.add_argument("--firmware", required=True, type=Path, help="Arquivo .swi a transferir.")
    parser.add_argument("--expected-version", help="Versao esperada; inferida do nome do arquivo se omitida.")
    parser.add_argument("--expected-model", choices=sorted(SUPPORTED_MODELS), help="Modelo esperado para validacao adicional.")
    parser.add_argument("--http-timeout", type=float, default=10.0, help="Timeout da consulta HTTP direta em segundos.")
    parser.add_argument("--reboot-timeout", type=int, default=DEFAULT_REBOOT_TIMEOUT, help="Espera maxima pelo ping, em segundos.")
    parser.add_argument("--transfer-timeout", type=int, default=DEFAULT_TRANSFER_TIMEOUT, help="Espera maxima da transferencia, em segundos.")
    parser.add_argument(
        "--transfer-stall-timeout",
        type=int,
        default=TRANSFER_STALL_TIMEOUT_SECONDS,
        help="Tempo maximo sem progresso na transferencia, em segundos.",
    )
    parser.add_argument("--driver-path", type=Path, help="ChromeDriver local; se omitido, usa Selenium Manager.")
    parser.add_argument(
        "--diagnostics-dir",
        type=Path,
        default=Path("diagnostics"),
        help="Destino usado somente com --capture-diagnostics.",
    )
    parser.add_argument(
        "--capture-diagnostics",
        action="store_true",
        help="Salva screenshot e estrutura da WebUI em falhas (pode conter dados operacionais).",
    )
    parser.add_argument("--insecure-tls", action="store_true", help="Aceita certificado HTTPS invalido (somente laboratorio).")
    parser.add_argument("--show-browser", action="store_true", help="Exibe o Chrome para diagnostico; por padrao ele fica oculto.")
    parser.add_argument("--json-progress", action="store_true", help="Emite eventos PROGRESS_JSON para integracao com o Sentinel.")
    parser.add_argument(
        "--allow-same-version",
        action="store_true",
        help="Permite reinstalar a versao ja detectada; requer --execute e confirmacao explicita.",
    )
    parser.add_argument(
        "--allow-downgrade",
        action="store_true",
        help="Permite instalar versao inferior; requer --execute e confirmacao explicita.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--webui-check",
        action="store_true",
        help="Consulta diretamente a pagina de login e valida modelo/versao, sem autenticar.",
    )
    mode.add_argument(
        "--preflight",
        action="store_true",
        help="Testa leitura HTTP, login, modelo e versao sem transferir firmware.",
    )
    mode.add_argument(
        "--wizard-check",
        action="store_true",
        help="Percorre o assistente ate a tela de arquivo, sem anexar, transferir ou reiniciar.",
    )
    mode.add_argument(
        "--save-check",
        action="store_true",
        help="Autentica e salva a configuracao pendente, sem upload ou reinicializacao.",
    )
    mode.add_argument("--execute", action="store_true", help="Autoriza a transferencia e o restart reais.")
    parser.add_argument(
        "--sentinel-approved",
        action="store_true",
        help="Informa que o usuario confirmou a operacao no pop-up autenticado do Sentinel.",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser


def validate_url(value: str) -> tuple[str, str]:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UpdateError("A URL deve usar http:// ou https:// e conter um host/IP valido.")
    if parsed.username or parsed.password:
        raise UpdateError("Nao inclua credenciais na URL.")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise UpdateError("Informe somente a origem do switch, sem caminho, consulta ou fragmento.")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise UpdateError("Nesta alpha, o switch deve ser informado diretamente por endereco IP.") from exc
    if address.version != 4:
        raise UpdateError("Nesta alpha, o switch deve ser informado por endereco IPv4.")
    if address.is_unspecified or address.is_loopback or address.is_multicast or address.is_link_local:
        raise UpdateError("O endereco IP informado nao e um destino valido para um switch.")
    normalized = f"{parsed.scheme}://{parsed.netloc}"
    return normalized, parsed.hostname


def validate_firmware(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise UpdateError(f"Firmware nao encontrado: {resolved}")
    if resolved.suffix.lower() != ".swi":
        raise UpdateError("A alpha aceita somente firmware com extensao .swi.")
    if resolved.stat().st_size == 0:
        raise UpdateError("O arquivo de firmware esta vazio.")
    if resolved.stat().st_size > MAX_FIRMWARE_BYTES:
        raise UpdateError(
            f"O firmware excede o limite de {MAX_FIRMWARE_BYTES // (1024 * 1024)} MiB da alpha."
        )
    return resolved


def infer_version_from_filename(path: Path) -> str | None:
    match = re.search(r"(?:1830|1930)[_-](\d+(?:\.\d+){2,3})", path.stem, re.IGNORECASE)
    return match.group(1) if match else None


def infer_model_from_filename(path: Path) -> str | None:
    match = re.search(r"(?:^|[_-])(1830|1930)(?:[_-]|$)", path.stem, re.IGNORECASE)
    return match.group(1) if match else None


def detect_supported_model(values: Iterable[str | None]) -> str | None:
    found: set[str] = set()
    for value in values:
        if not value:
            continue
        for model in SUPPORTED_MODELS:
            if re.search(rf"(?<!\d){model}(?!\d)", value, re.IGNORECASE):
                found.add(model)
    if len(found) > 1:
        raise UpdateError(f"Identificacao de modelo ambigua: {', '.join(sorted(found))}.")
    return next(iter(found), None)


def normalize_version(value: str) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"^(?:firmware|software|version|versao|v)\s*[:=-]?\s*", "", normalized)
    return normalized.replace("_", ".")


def version_matches(expected: str, observed: str | None) -> bool:
    if not observed:
        return False
    expected_normalized = normalize_version(expected)
    observed_normalized = normalize_version(observed)
    # O Aruba 1930 publica, por exemplo, 3.4.0.0 (6) para a imagem 3.4.0.6.
    observed_normalized = re.sub(
        r"(?<!\d)(\d+\.\d+\.\d+)\.0\s*\(\s*(\d+)\s*\)",
        r"\1.\2",
        observed_normalized,
    )
    pattern = rf"(?<![0-9a-z])v?{re.escape(expected_normalized)}(?![0-9a-z])"
    return bool(re.search(pattern, observed_normalized, re.IGNORECASE))


def extract_version(value: str | None) -> str | None:
    if not value:
        return None
    # Preserva '_' para que o modelo em "InstantOn_1930_..." nao seja
    # interpretado como o primeiro componente de uma versao.
    normalized = value.strip().lower()
    normalized = re.sub(
        r"(?<!\d)(\d+\.\d+\.\d+)\.0\s*\(\s*(\d+)\s*\)",
        r"\1.\2",
        normalized,
    )
    matches = re.findall(r"(?<!\d)(\d+(?:\.\d+){2,3})(?!\d)", normalized)
    return matches[-1] if matches else None


def version_key(value: str) -> tuple[int, int, int, int]:
    numbers = [int(part) for part in value.split(".")]
    return tuple((numbers + [0] * 4)[:4])  # type: ignore[return-value]


def final_version_matches(expected: str, observed: str | None) -> bool:
    """Confirma a familia major.minor.patch na verificacao apos o restart."""
    expected_version = extract_version(expected)
    observed_version = extract_version(observed)
    if not expected_version or not observed_version:
        return False
    return version_key(expected_version)[:3] == version_key(observed_version)[:3]


def release_version(value: str) -> str:
    """Retorna a versao operacional exibida ao usuario, como 3.4.0."""
    extracted = extract_version(value)
    if not extracted:
        return normalize_version(value)
    return ".".join(extracted.split(".")[:3])


def resolve_firmware_metadata(
    firmware: Path,
    expected_model: str | None = None,
    expected_version: str | None = None,
) -> tuple[Path, str, str]:
    """Valida o arquivo e resolve modelo/versao sem acessar o switch."""
    resolved = validate_firmware(firmware)
    target_version = expected_version or infer_version_from_filename(resolved)
    if not target_version:
        raise UpdateError("Nao foi possivel inferir a versao; informe --expected-version.")
    if not re.fullmatch(r"\d+(?:\.\d+){2,3}(?:[-._a-zA-Z0-9]+)?", target_version):
        raise UpdateError("A versao esperada deve ter formato semelhante a 3.4.0.6.")

    firmware_model = infer_model_from_filename(resolved)
    if expected_model and firmware_model and expected_model != firmware_model:
        raise UpdateError(
            f"O nome do firmware indica Aruba {firmware_model}, "
            f"mas o modelo esperado indica {expected_model}."
        )
    target_model = expected_model or firmware_model
    if not target_model or target_model not in SUPPORTED_MODELS:
        raise UpdateError("O firmware deve identificar um Aruba 1830 ou 1930 suportado.")
    return resolved, target_model, target_version


def classify_update(expected_version: str, observed: str | None) -> tuple[str, str]:
    """Classifica a operacao; sem versao atual confiavel, bloqueia por seguranca."""
    current_version = extract_version(observed)
    if not current_version:
        raise UpdateError("Nao foi possivel identificar a versao atual do switch com seguranca.")
    if version_matches(expected_version, observed):
        return "same_version", current_version
    if version_key(expected_version) < version_key(current_version):
        return "downgrade", current_version
    return "update", current_version


def assess_update(
    url: str,
    firmware: Path,
    *,
    expected_model: str | None = None,
    expected_version: str | None = None,
    http_timeout: float = 10.0,
    insecure_tls: bool = False,
) -> UpdateAssessment:
    """Executa o preflight publico e devolve a decisao para a UI/agendador."""
    normalized_url, host = validate_url(url)
    if http_timeout <= 0:
        raise UpdateError("O timeout HTTP deve ser maior que zero.")
    resolved, target_model, target_version = resolve_firmware_metadata(
        firmware,
        expected_model,
        expected_version,
    )
    identity = fetch_web_identity(normalized_url, http_timeout, insecure_tls)
    if identity.model != target_model:
        raise UpdateError(
            f"A WebUI indica Aruba {identity.model or 'desconhecido'}, "
            f"mas o firmware e para Aruba {target_model}."
        )
    decision, current_version = classify_update(target_version, identity.sys_descr)
    final_parsed = urlparse(identity.url)
    detected_url = f"{final_parsed.scheme}://{final_parsed.netloc}"
    return UpdateAssessment(
        url=detected_url,
        host=host,
        firmware=resolved,
        expected_model=target_model,
        expected_version=target_version,
        current_model=identity.model,
        current_version=current_version,
        decision=decision,
        identity=identity,
    )


def fetch_web_identity(url: str, timeout: float, insecure_tls: bool) -> WebIdentity:
    """Consulta modelo e versao diretamente, sem navegador e sem credenciais."""
    context = ssl._create_unverified_context() if insecure_tls else ssl.create_default_context()
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context))
    request = Request(url, headers={"User-Agent": f"ATT-Switches/{__version__}"})
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(2 * 1024 * 1024)
            charset = response.headers.get_content_charset() or "utf-8"
            html = raw.decode(charset, errors="replace")
            final_url = response.geturl()
    except HTTPError as exc:
        raise UpdateError(f"A WebUI respondeu HTTP {exc.code} ao consultar identificacao.") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Nao foi possivel consultar a WebUI diretamente: {exc}") from exc

    original_host = urlparse(url).hostname
    final_parsed = urlparse(final_url)
    if final_parsed.scheme not in {"http", "https"} or final_parsed.hostname != original_host:
        raise UpdateError("A WebUI redirecionou para outro destino; consulta bloqueada por seguranca.")

    parser = LoginPageParser()
    parser.feed(html)
    required_ids = {"inputUsername", "inputPassword", "submitButton"}
    missing = sorted(required_ids - parser.element_ids)
    if missing:
        raise UpdateError(f"Pagina de login nao reconhecida; elementos ausentes: {', '.join(missing)}.")
    def clean_text(value: str) -> str:
        return re.sub(r"\s+", " ", value.replace("\ufffd", " ").replace("\xa0", " ")).strip()

    sys_name = clean_text(parser.fields.get("sysName", ""))
    sys_descr = clean_text(parser.fields.get("sysDescr", ""))
    model = detect_supported_model((parser.title, sys_descr))
    return WebIdentity(
        url=final_url,
        title=parser.title,
        sys_name=sys_name,
        sys_descr=sys_descr,
        model=model,
    )


def wait_for_web_identity(
    url: str,
    request_timeout: float,
    insecure_tls: bool,
    max_wait: int = 120,
) -> WebIdentity:
    deadline = time.monotonic() + max_wait
    last_error: UpdateError | None = None
    while time.monotonic() < deadline:
        try:
            return fetch_web_identity(url, request_timeout, insecure_tls)
        except UpdateError as exc:
            last_error = exc
            remaining = max(0, int(deadline - time.monotonic()))
            LOGGER.info("WebUI ainda indisponivel; nova tentativa em 5s (restam %ss).", remaining)
            time.sleep(min(5, max(0, remaining)))
    raise UpdateError(
        "O switch respondeu ao ping, mas a WebUI nao retornou em ate "
        f"{max_wait}s. Ultimo erro: {last_error}"
    )


def ping_once(host: str, timeout_seconds: int = 2) -> bool:
    if os.name == "nt":
        command = ["ping", "-n", "1", "-w", str(timeout_seconds * 1000), host]
    else:
        command = ["ping", "-c", "1", "-W", str(timeout_seconds), host]
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=timeout_seconds + 2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def wait_for_ping_after_restart(
    host: str,
    timeout: int,
    interval: int = 5,
    reporter: ProgressReporter | None = None,
) -> None:
    LOGGER.info("Aguardando o inicio da reinicializacao por 15 segundos...")
    time.sleep(15)
    deadline = time.monotonic() + timeout
    attempt = 0
    if reporter:
        reporter.emit(
            "waiting_ping",
            70,
            f"Aguardando resposta por ping. Restam {timeout} segundos.",
        )
    while time.monotonic() < deadline:
        attempt += 1
        if ping_once(host):
            LOGGER.info("O switch voltou a responder ao ping (tentativa %s).", attempt)
            return
        remaining = max(0, int(deadline - time.monotonic()))
        LOGGER.info("Sem resposta ao ping; restam ate %ss.", remaining)
        if reporter:
            elapsed_ratio = 1 - (remaining / timeout)
            reporter.emit(
                "waiting_ping",
                min(84, 70 + int(max(0, elapsed_ratio) * 14)),
                f"Aguardando resposta por ping. Restam {remaining} segundos.",
            )
        time.sleep(min(interval, max(0, remaining)))
    raise UpdateNeedsReview(
        "O firmware foi transferido e o restart foi enviado, mas o switch nao respondeu "
        "em ate sete minutos. A atualizacao aguarda nova verificacao no Sentinel."
    )


class ArubaWebUpdater:
    """Automacao WebUI conhecida para Aruba Instant On 1830/1930."""

    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        driver_path: Path | None,
        insecure_tls: bool,
        show_browser: bool,
        diagnostics_dir: Path,
    ) -> None:
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.service import Service as ChromeService
            from selenium.webdriver.common.by import By
            from selenium.common.exceptions import (
                ElementClickInterceptedException,
                NoSuchFrameException,
                StaleElementReferenceException,
                WebDriverException,
            )
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.support.ui import Select, WebDriverWait
        except ModuleNotFoundError as exc:
            raise UpdateError("Selenium nao esta instalado. Execute: python -m pip install -r requirements.txt") from exc

        self.By = By
        self.EC = EC
        self.Select = Select
        self.ElementClickInterceptedException = ElementClickInterceptedException
        self.frame_errors = (NoSuchFrameException, StaleElementReferenceException, WebDriverException)
        options = webdriver.ChromeOptions()
        if show_browser:
            options.add_argument("--start-maximized")
        else:
            options.add_argument("--headless=new")
            options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-sync")
        options.add_argument("--no-first-run")
        if insecure_tls:
            LOGGER.warning("Certificados HTTPS invalidos serao aceitos neste teste.")
            options.set_capability("acceptInsecureCerts", True)
            options.add_argument("--ignore-certificate-errors")
        service = (
            ChromeService(executable_path=str(driver_path.resolve()))
            if driver_path
            else ChromeService()
        )
        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.set_page_load_timeout(90)
        self.wait = WebDriverWait(self.driver, 60)
        self.url = url
        self.username = username
        self.password = password
        self.diagnostics_dir = diagnostics_dir.resolve()

    def close(self) -> None:
        try:
            self.driver.quit()
        except Exception:  # pragma: no cover - depende do estado externo do navegador
            LOGGER.warning("Nao foi possivel encerrar o navegador de forma limpa.")

    def login(self) -> None:
        LOGGER.info("Abrindo %s e autenticando...", self.url)
        self.driver.get(self.url)
        expected_host = urlparse(self.url).hostname
        current_host = urlparse(self.driver.current_url).hostname
        if current_host != expected_host:
            raise UpdateError(
                "A WebUI redirecionou o navegador para outro destino; credenciais nao foram enviadas."
            )
        current_url = urlparse(self.driver.current_url)
        if current_url.scheme in {"http", "https"}:
            self.url = f"{current_url.scheme}://{current_url.netloc}"
        username = self.wait.until(self.EC.presence_of_element_located((self.By.ID, "inputUsername")))
        password = self.wait.until(self.EC.presence_of_element_located((self.By.ID, "inputPassword")))
        username.clear()
        username.send_keys(self.username)
        password.clear()
        password.send_keys(self.password)
        self.wait.until(self.EC.element_to_be_clickable((self.By.ID, "submitButton"))).click()
        try:
            self.wait.until(self.EC.presence_of_element_located((self.By.ID, "item_1660")))
        except Exception as exc:
            raise UpdateError("Login nao confirmado ou interface do switch nao reconhecida.") from exc

    def detected_model(self, identity_text: str = "") -> str:
        body_text = ""
        try:
            body_text = self.driver.find_element(self.By.TAG_NAME, "body").text[:5000]
        except Exception:
            pass
        model = detect_supported_model((identity_text, self.driver.title, body_text))
        if not model:
            raise UpdateError(
                "Modelo nao identificado como Aruba 1830/1930. A execucao foi bloqueada antes do upload."
            )
        return model

    def read_web_version(self) -> str | None:
        LOGGER.info("Consultando a versao apresentada pela WebUI...")
        try:
            dashboard = self.driver.find_elements(self.By.ID, "item_1010")
            if dashboard:
                dashboard[0].click()
                time.sleep(2)
        except Exception:
            LOGGER.debug("Nao foi possivel acionar o Dashboard; tentando ler a pagina atual.")

        candidate_xpaths = (
            "//*[normalize-space()='Software Version']/following-sibling::*[1]",
            "//*[normalize-space()='Firmware Version']/following-sibling::*[1]",
            "//*[contains(@id,'oftware') and contains(@id,'ersion')]",
            "//*[contains(@id,'irmware') and contains(@id,'ersion')]",
        )
        for xpath in candidate_xpaths:
            for element in self.driver.find_elements(self.By.XPATH, xpath):
                text = element.text.strip()
                if re.search(r"\d+\.\d+\.\d+", text):
                    return text

        try:
            body = self.driver.find_element(self.By.TAG_NAME, "body").text
        except Exception:
            return None
        match = re.search(
            r"(?:Software|Firmware)\s+Version\s*[:\r\n-]*\s*(v?\d+(?:\.\d+){2,3}(?:[-._a-z0-9]+)?)",
            body,
            re.IGNORECASE,
        )
        return match.group(1) if match else None

    def save_configuration(
        self,
        timeout: int = 30,
        pending_timeout: int = 0,
    ) -> bool:
        """Persiste a configuracao corrente e confirma que o aviso de pendencia sumiu."""
        LOGGER.info("Verificando alteracoes pendentes no botao Save Configuration...")
        pending_deadline = time.monotonic() + max(0, pending_timeout)
        lookup_timeout = max(10, pending_timeout)
        try:
            button = self._find_element_anywhere(
                ((self.By.ID, "btnTopSave"),),
                "o botao Save Configuration",
                timeout=lookup_timeout,
                require_visible=False,
            )
        except UpdateError:
            LOGGER.info(
                "O botao Save Configuration nao apareceu em ate %ss; "
                "nao ha pendencia indicada.",
                lookup_timeout,
            )
            return False
        while True:
            try:
                pending = button.is_displayed() and button.is_enabled()
            except self.frame_errors:
                try:
                    button = self._find_element_anywhere(
                        ((self.By.ID, "btnTopSave"),),
                        "o botao Save Configuration",
                        timeout=1,
                        require_visible=False,
                    )
                    pending = button.is_displayed() and button.is_enabled()
                except (UpdateError, *self.frame_errors):
                    pending = False
            if pending or time.monotonic() >= pending_deadline:
                break
            time.sleep(0.25)
        if not pending:
            LOGGER.info("Nao ha configuracao pendente para salvar.")
            return False

        self.driver.execute_script("arguments[0].click();", button)
        deadline = time.monotonic() + timeout
        confirmation_clicked = False
        while time.monotonic() < deadline:
            self.driver.switch_to.default_content()

            if not confirmation_clicked:
                for confirmation_id in ("modalButtonOk", "modalStatusButtonOk"):
                    for confirmation in self.driver.find_elements(self.By.ID, confirmation_id):
                        try:
                            if not (confirmation.is_displayed() and confirmation.is_enabled()):
                                continue
                            modal = confirmation.find_element(
                                self.By.XPATH,
                                "ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' modal ')][1]",
                            )
                            modal_text = modal.text.casefold()
                            if "save" in modal_text or "configuration" in modal_text:
                                confirmation.click()
                                confirmation_clicked = True
                                break
                        except self.frame_errors:
                            continue
                    if confirmation_clicked:
                        break

            buttons = self.driver.find_elements(self.By.ID, "btnTopSave")
            still_pending = False
            for current in buttons:
                try:
                    classes = (current.get_attribute("class") or "").casefold()
                    aria_disabled = (current.get_attribute("aria-disabled") or "").casefold()
                    if (
                        current.is_displayed()
                        and current.is_enabled()
                        and "disabled" not in classes
                        and aria_disabled != "true"
                    ):
                        still_pending = True
                        break
                except self.frame_errors:
                    continue
            if not still_pending:
                LOGGER.info("Configuracao salva; o indicador de alteracoes pendentes foi removido.")
                return True
            time.sleep(0.5)

        raise UpdateError(
            "O botao Save Configuration foi acionado, mas a WebUI nao confirmou o salvamento "
            f"em ate {timeout}s."
        )

    def _search_frame_tree(
        self,
        locator: tuple[str, str],
        clickable: bool,
        require_visible: bool,
        depth: int = 0,
    ):
        """Procura um elemento no documento atual e recursivamente em frames."""
        try:
            for element in self.driver.find_elements(*locator):
                try:
                    visible = element.is_displayed()
                    if (visible or not require_visible) and (
                        not clickable or (visible and element.is_enabled())
                    ):
                        return element
                except self.frame_errors:
                    continue

            if depth >= 6:
                return None

            frames = self.driver.find_elements(self.By.CSS_SELECTOR, "iframe, frame")
            for index in range(len(frames)):
                found = None
                switched = False
                try:
                    # Rele a lista porque interfaces antigas recriam frames durante o carregamento.
                    current_frames = self.driver.find_elements(self.By.CSS_SELECTOR, "iframe, frame")
                    if index >= len(current_frames):
                        continue
                    self.driver.switch_to.frame(current_frames[index])
                    switched = True
                    found = self._search_frame_tree(locator, clickable, require_visible, depth + 1)
                    if found is not None:
                        return found
                except self.frame_errors:
                    pass
                finally:
                    if switched and found is None:
                        try:
                            self.driver.switch_to.parent_frame()
                        except self.frame_errors:
                            self.driver.switch_to.default_content()
        except self.frame_errors:
            return None
        return None

    def _find_element_anywhere(
        self,
        locators: Iterable[tuple[str, str]],
        description: str,
        timeout: int = 60,
        clickable: bool = False,
        require_visible: bool = True,
    ):
        deadline = time.monotonic() + timeout
        locator_list = tuple(locators)
        while time.monotonic() < deadline:
            for locator in locator_list:
                try:
                    self.driver.switch_to.default_content()
                    element = self._search_frame_tree(locator, clickable, require_visible)
                    if element is not None:
                        return element
                except self.frame_errors:
                    continue
            time.sleep(0.25)
        raise UpdateError(
            f"Nao foi possivel localizar {description} em ate {timeout}s, "
            "inclusive dentro dos frames da WebUI."
        )

    def _click_anywhere(
        self,
        locators: Iterable[tuple[str, str]],
        description: str,
        timeout: int = 60,
    ) -> None:
        deadline = time.monotonic() + timeout
        locator_list = tuple(locators)
        while time.monotonic() < deadline:
            remaining = max(1, int(deadline - time.monotonic()))
            try:
                element = self._find_element_anywhere(
                    locator_list,
                    description,
                    min(5, remaining),
                    clickable=True,
                )
                try:
                    element.click()
                except self.ElementClickInterceptedException:
                    self.driver.execute_script("arguments[0].click();", element)
                return
            except self.frame_errors:
                time.sleep(0.25)
            except UpdateError:
                time.sleep(0.25)
        raise UpdateError(
            f"Nao foi possivel clicar em {description} em ate {timeout}s; "
            "a WebUI recriou o controle durante o carregamento."
        )

    def _click_id(self, element_id: str, description: str | None = None) -> None:
        self._click_anywhere(
            ((self.By.ID, element_id),),
            description or f"o elemento #{element_id}",
        )

    def _ensure_radio_selected(
        self,
        radio_id: str,
        label_id: str,
        description: str,
    ) -> None:
        if self._radio_selected(radio_id, description, timeout=60):
            LOGGER.info("%s ja esta selecionado.", description)
            return

        self._click_anywhere(
            (
                (self.By.ID, label_id),
                (self.By.CSS_SELECTOR, f"label[for='{radio_id}']"),
            ),
            f"o rotulo de {description}",
        )
        if not self._radio_selected(radio_id, description, timeout=10):
            raise UpdateError(f"A interface nao confirmou a selecao de {description}.")

    def _radio_selected(self, radio_id: str, description: str, timeout: int) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(1, int(deadline - time.monotonic()))
            try:
                radio = self._find_element_anywhere(
                    ((self.By.ID, radio_id),),
                    description,
                    timeout=min(5, remaining),
                    require_visible=False,
                )
                return bool(radio.is_selected())
            except (UpdateError, *self.frame_errors):
                time.sleep(0.25)
        raise UpdateError(
            f"Nao foi possivel confirmar {description}; a WebUI recriou o controle repetidamente."
        )

    def _ensure_select_option(
        self,
        select_id: str,
        visible_text: str,
        description: str,
    ) -> None:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                select_element = self._find_element_anywhere(
                    ((self.By.ID, select_id),),
                    description,
                    timeout=5,
                    require_visible=False,
                )
                current_text = self.Select(select_element).first_selected_option.text.strip()
                if current_text.casefold() == visible_text.casefold():
                    LOGGER.info("%s ja esta selecionada.", description)
                    return

                # A WebUI usa um dropdown visual sobre um <select> nativo oculto.
                changed = self.driver.execute_script(
                    """
                    const select = arguments[0];
                    const expected = arguments[1].trim().toLocaleLowerCase();
                    const option = Array.from(select.options).find(
                      item => item.text.trim().toLocaleLowerCase() === expected
                    );
                    if (!option) return false;
                    select.value = option.value;
                    option.selected = true;
                    select.dispatchEvent(new Event('input', {bubbles: true}));
                    select.dispatchEvent(new Event('change', {bubbles: true}));
                    return true;
                    """,
                    select_element,
                    visible_text,
                )
                if not changed:
                    time.sleep(0.25)
                    continue
                time.sleep(0.25)
            except (UpdateError, *self.frame_errors):
                time.sleep(0.25)
        raise UpdateError(
            f"Nao foi possivel confirmar {description}; a WebUI recriou o controle repetidamente."
        )

    def capture_diagnostics(self, reason: str) -> Path | None:
        """Salva screenshot e metadados estruturais; nunca salva valores de inputs."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = self.diagnostics_dir / stamp
        try:
            target.mkdir(parents=True, exist_ok=False)
            self.driver.switch_to.default_content()
            self.driver.save_screenshot(str(target / "screen.png"))
            structure = self.driver.execute_script(
                """
                const describe = (doc, path, depth) => {
                  const result = [];
                  const interactive = doc.querySelectorAll(
                    'button, label, select, a, input[id], iframe, frame'
                  );
                  for (const el of interactive) {
                    const style = window.getComputedStyle(el);
                    result.push({
                      frame: path,
                      tag: el.tagName.toLowerCase(),
                      id: el.id || '',
                      name: el.name || '',
                      type: el.type || '',
                      checked: ['radio', 'checkbox'].includes(el.type) ? el.checked : null,
                      disabled: Boolean(el.disabled),
                      visible: style.display !== 'none' && style.visibility !== 'hidden',
                      selectedText: el.tagName === 'SELECT' && el.selectedIndex >= 0
                        ? (el.options[el.selectedIndex]?.text || '').trim()
                        : '',
                      text: ['INPUT'].includes(el.tagName)
                        ? ''
                        : (el.innerText || el.textContent || '').trim().slice(0, 160)
                    });
                  }
                  if (depth >= 6) return result;
                  const frames = doc.querySelectorAll('iframe, frame');
                  frames.forEach((frame, index) => {
                    try {
                      if (frame.contentDocument) {
                        result.push(...describe(frame.contentDocument, `${path}/${index}`, depth + 1));
                      }
                    } catch (_) {}
                  });
                  return result;
                };
                return describe(document, 'top', 0);
                """
            )
            payload = {
                "reason": reason,
                "url": self.driver.current_url,
                "title": self.driver.title,
                "elements": structure,
            }
            (target / "structure.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            LOGGER.error("Diagnostico da WebUI salvo em: %s", target)
            return target
        except Exception as exc:  # pragma: no cover - depende do estado do navegador
            LOGGER.warning("Nao foi possivel salvar o diagnostico da WebUI: %s", exc)
            return None

    def open_update_wizard(self) -> None:
        LOGGER.info("Abrindo Maintenance > Backup and Update Files...")
        self._click_id("item_1660", "o menu Maintenance")
        self._click_id("item_1660_1680", "a opcao Backup and Update Files")

        self._ensure_radio_selected(
            "rbOperationType_0",
            "lblrbOperationType_0",
            "a opcao Update",
        )
        self._click_id("btnNext", "o botao Next apos Update")

        self._ensure_select_option(
            "slctFileType",
            "Backup Image",
            "a selecao Backup Image",
        )
        self._click_id("btnNext", "o botao Next apos Backup Image")

        # A transferencia do arquivo .swi e feita pela opcao HTTP da WebUI.
        self._ensure_radio_selected(
            "rbTransferProtocol_0",
            "lblrbTransferProtocol_0",
            "o protocolo HTTP",
        )
        self._click_id("btnNext", "o botao Next apos HTTP")

    def _locate_firmware_input(self):
        frame = self._find_element_anywhere(
            ((self.By.ID, "uploadFrame"),),
            "o frame de upload",
        )
        self.driver.switch_to.frame(frame)
        try:
            file_input = self._find_element_anywhere(
                (
                    (self.By.ID, "srcFileName"),
                    (self.By.CSS_SELECTOR, "input[type='file']"),
                ),
                "o campo de arquivo do firmware",
                require_visible=False,
            )
            return file_input
        except Exception:
            self.driver.switch_to.default_content()
            raise

    def validate_upload_field(self) -> None:
        LOGGER.info("Validando o campo de upload sem anexar arquivo...")
        self._locate_firmware_input()
        self.driver.switch_to.default_content()

    def attach_firmware(self, firmware: Path) -> None:
        LOGGER.info("Anexando firmware ao campo de upload...")
        try:
            file_input = self._locate_firmware_input()
            self.driver.execute_script(
                "arguments[0].style.display='block'; arguments[0].style.visibility='visible';", file_input
            )
            file_input.send_keys(str(firmware))
        finally:
            self.driver.switch_to.default_content()

    def _session_expired(self) -> bool:
        return bool(self.driver.find_elements(self.By.ID, "inputUsername"))

    def start_transfer_and_wait(
        self,
        timeout: int,
        reporter: ProgressReporter,
        stall_timeout: int = TRANSFER_STALL_TIMEOUT_SECONDS,
    ) -> None:
        LOGGER.info("Iniciando a transferencia do firmware...")
        transfer_started_at = time.monotonic()
        last_progress_at = transfer_started_at
        transferred_bytes = 0
        total_bytes = 0
        last_progress_number = 0
        consecutive_ping_failures = 0
        host = str(urlparse(self.url).hostname or "").strip()
        self._click_id("buttonTransferProtocolHTTP")
        deadline = time.monotonic() + timeout
        last_message = ""
        while time.monotonic() < deadline:
            snapshot = self.driver.execute_script(
                """
                const text = selector => {
                  const element = document.querySelector(selector);
                  return element
                    ? String(element.innerText || element.textContent || '').trim()
                    : '';
                };
                return {
                  sessionExpired: Boolean(document.getElementById('inputUsername')),
                  status: text('#lblStatusModal'),
                  error: text('#lblErrorModal'),
                  progress: text('#loadingBar .ldBar-label')
                };
                """
            ) or {}
            if snapshot.get("sessionExpired"):
                raise UpdateError("A sessao do switch expirou durante a transferencia.")
            status = str(snapshot.get("status") or "").strip()
            error = str(snapshot.get("error") or "").strip()
            progress = str(snapshot.get("progress") or "").strip()
            progress_number = 0
            transfer_match = re.search(
                r"Copying\s+(\d+)\s*/\s*(\d+)\s*Bytes",
                status,
                flags=re.IGNORECASE,
            )
            if transfer_match:
                transferred = int(transfer_match.group(1))
                total = int(transfer_match.group(2))
                if transferred > transferred_bytes:
                    last_progress_at = time.monotonic()
                transferred_bytes = transferred
                total_bytes = total
                progress_number = int((transferred / total) * 100) if total else 0
                transferred_mb = f"{transferred / 1_000_000:.2f}".replace(".", ",")
                total_mb = f"{total / 1_000_000:.2f}".replace(".", ",")
                status = (
                    f"Transferindo {transferred_mb} MB de {total_mb} MB "
                    f"({progress_number}%)"
                )
                # Alguns modelos mantêm o label visual da barra em 0 durante
                # toda a cópia. Neste caso, o contador de bytes é a fonte
                # confiável e já contém a porcentagem calculada.
                progress_detail = ""
            else:
                match = re.search(r"\d+(?:[.,]\d+)?", progress)
                if match:
                    progress_number = int(float(match.group(0).replace(",", ".")))
                    if progress_number > last_progress_number:
                        last_progress_at = time.monotonic()
                progress_detail = (
                    f"{progress.rstrip('%')}%" if progress_number > 0 else ""
                )
            last_progress_number = max(last_progress_number, progress_number)
            message = " | ".join(
                part for part in (status, progress_detail, error) if part
            )
            if message and message != last_message:
                LOGGER.info("Transferencia: %s", message)
                reporter.emit("transfer", 35 + int(progress_number * 0.25), message)
                last_message = message
            lowered = f"{status} {error}".lower()
            if "operation succeeded" in lowered or "transfer succeeded" in lowered:
                elapsed = max(0.001, time.monotonic() - transfer_started_at)
                completed_bytes = total_bytes or transferred_bytes
                average_kbps = (completed_bytes / 1000) / elapsed
                elapsed_seconds = int(round(elapsed))
                minutes, seconds = divmod(elapsed_seconds, 60)
                LOGGER.info(
                    "Transferencia concluida com sucesso em %02d:%02d; taxa media %.1f KB/s.",
                    minutes,
                    seconds,
                    average_kbps,
                )
                return
            if any(word in lowered for word in ("failed", "failure", "invalid", "error")):
                elapsed = max(0.001, time.monotonic() - transfer_started_at)
                average_kbps = (transferred_bytes / 1000) / elapsed
                LOGGER.warning(
                    "Transferencia interrompida apos %.2f MB; taxa media %.1f KB/s.",
                    transferred_bytes / 1_000_000,
                    average_kbps,
                )
                raise UpdateError(f"O switch informou falha na transferencia: {message}")
            stalled_for = time.monotonic() - last_progress_at
            if stalled_for >= stall_timeout:
                raise UpdateError(
                    f"A transferencia ficou sem progresso por {stall_timeout} segundos e foi "
                    "interrompida para permitir uma nova tentativa."
                )

            next_status_poll = min(
                deadline,
                time.monotonic() + TRANSFER_STATUS_POLL_SECONDS,
            )
            while time.monotonic() < next_status_poll:
                remaining = next_status_poll - time.monotonic()
                time.sleep(min(TRANSFER_CONNECTIVITY_POLL_SECONDS, remaining))
                if not host:
                    continue
                if ping_once(host):
                    consecutive_ping_failures = 0
                    continue
                consecutive_ping_failures += 1
                LOGGER.warning(
                    "Switch sem resposta durante a transferencia (%s/%s).",
                    consecutive_ping_failures,
                    TRANSFER_CONNECTIVITY_FAILURE_LIMIT,
                )
                if consecutive_ping_failures >= TRANSFER_CONNECTIVITY_FAILURE_LIMIT:
                    raise UpdateError(
                        "A conexao com o switch foi perdida durante a transferencia do "
                        "firmware. A tentativa foi interrompida com seguranca."
                    )
        raise UpdateError("Timeout aguardando a transferencia atingir 100% e concluir.")

    def restart(self) -> None:
        LOGGER.info("Acionando o restart do switch...")
        self._click_id("modalBackupReset")


def confirm_execution(
    args: argparse.Namespace,
    firmware: Path,
    expected_version: str,
    same_version: bool,
    downgrade: bool,
) -> None:
    print("\nATENCAO: esta operacao transferira firmware e reiniciara um switch real.")
    print(f"  Switch: {args.url}")
    print(f"  Firmware: {firmware}")
    print(f"  Versao esperada: {expected_version}")
    if same_version:
        print("  AVISO: a mesma versao ja foi detectada e sera reinstalada para homologacao.")
    if downgrade:
        print("  AVISO: esta operacao instalara uma versao anterior do firmware.")
    if args.sentinel_approved:
        LOGGER.info("Confirmacao recebida pelo Sentinel; prompt textual dispensado.")
        return
    if same_version:
        required = f"REINSTALAR {expected_version}"
    elif downgrade:
        required = f"REBAIXAR {expected_version}"
    else:
        required = "ATUALIZAR"
    answer = input(f"Digite {required} para continuar: ").strip()
    if answer != required:
        raise UpdateError("Operacao cancelada pelo usuario.")


def collect_switch_password() -> str:
    switch_password = getpass("Senha da interface web do switch: ")
    if not switch_password:
        raise UpdateError("A senha da interface web nao pode ficar vazia.")
    return switch_password


def run(
    args: argparse.Namespace,
    *,
    switch_password: str | None = None,
    reporter: ProgressReporter | None = None,
) -> None:
    url, host = validate_url(args.url)
    args.url = url
    firmware, expected_model, expected_version = resolve_firmware_metadata(
        args.firmware,
        args.expected_model,
        args.expected_version,
    )
    if (
        args.reboot_timeout <= 0
        or args.transfer_timeout <= 0
        or args.transfer_stall_timeout <= 0
        or args.http_timeout <= 0
    ):
        raise UpdateError("Os timeouts devem ser maiores que zero.")
    if args.sentinel_approved and not args.execute:
        raise UpdateError("--sentinel-approved so pode ser usado junto com --execute.")
    if args.allow_same_version and not args.execute:
        raise UpdateError("--allow-same-version so pode ser usado junto com --execute.")
    if args.allow_downgrade and not args.execute:
        raise UpdateError("--allow-downgrade so pode ser usado junto com --execute.")

    args.username = str(args.username or "").strip()
    if not args.username:
        raise UpdateError("O usuario da interface web nao pode ficar vazio.")

    reporter = reporter or ProgressReporter(args.json_progress)

    if args.webui_check:
        reporter.emit("identity", 10, "Consultando modelo e versao via HTTP direto")
        snapshot = fetch_web_identity(url, args.http_timeout, args.insecure_tls)
        if snapshot.model != expected_model:
            raise UpdateError(
                f"A WebUI indica Aruba {snapshot.model or 'desconhecido'}, "
                f"mas o modelo esperado e Aruba {expected_model}."
            )
        reporter.emit("complete", 100, "Identificacao publica validada")
        print("WebUI validada por HTTP direto, sem navegador, autenticacao ou alteracoes.")
        print(f"URL final: {snapshot.url}")
        print(f"Titulo: {snapshot.title}")
        print(f"Modelo identificado: Aruba {snapshot.model}")
        print(f"sysName: {snapshot.sys_name or '-'}")
        print(f"sysDescr: {snapshot.sys_descr or '-'}")
        print(f"Versao esperada reconhecida: {version_matches(expected_version, snapshot.sys_descr)}")
        return

    if not args.preflight and not args.wizard_check and not args.save_check and not args.execute:
        print("Plano alpha validado; nenhuma conexao foi aberta e nenhuma alteracao foi feita.")
        print(f"Switch: {url}")
        print(f"Firmware: {firmware}")
        print(f"Modelo esperado: Aruba {expected_model}")
        print(f"Versao esperada: {expected_version}")
        print("Modelos permitidos: Aruba 1830 e 1930")
        print("Use --preflight para testar as consultas, --wizard-check para testar o assistente,")
        print("--save-check para persistir uma configuracao pendente ou --execute para atualizar.")
        return

    reporter.emit("identity", 10, "Consultando modelo e versao inicial via HTTP direto")
    initial_identity = fetch_web_identity(url, args.http_timeout, args.insecure_tls)
    if initial_identity.model != expected_model:
        raise UpdateError(
            f"A WebUI indica Aruba {initial_identity.model or 'desconhecido'}, "
            f"mas o firmware e para Aruba {expected_model}."
        )
    decision, current_version = classify_update(expected_version, initial_identity.sys_descr)
    same_version = decision == "same_version"
    downgrade = decision == "downgrade"
    if args.execute and same_version and not args.allow_same_version:
        raise UpdateError(
            "A versao esperada ja esta instalada. Para a reinstalacao controlada de laboratorio, "
            "use --allow-same-version e confirme novamente a operacao."
        )
    if args.execute and downgrade and not args.allow_downgrade:
        raise UpdateError(
            f"Downgrade detectado: atual={current_version}, destino={expected_version}. "
            "Use --allow-downgrade somente em laboratorio e confirme novamente a operacao."
        )

    if switch_password is None:
        switch_password = collect_switch_password()
    elif not switch_password:
        raise UpdateError("A senha da interface web nao pode ficar vazia.")

    updater: ArubaWebUpdater | None = None

    try:
        reporter.emit("authentication", 20, "Autenticando na WebUI")
        updater = ArubaWebUpdater(
            url=url,
            username=args.username,
            password=switch_password,
            driver_path=args.driver_path,
            insecure_tls=args.insecure_tls,
            show_browser=args.show_browser,
            diagnostics_dir=args.diagnostics_dir,
        )
        updater.login()
        detected_model = updater.detected_model(initial_identity.sys_descr)
        if detected_model != expected_model:
            raise UpdateError(
                f"Modelo detectado ({detected_model}) diferente do firmware/esperado ({expected_model})."
            )
        LOGGER.info("Modelo autorizado detectado: Aruba %s.", detected_model)
        initial_web_version = updater.read_web_version()
        LOGGER.info("Versao inicial na WebUI: %s", initial_web_version or "nao localizada")

        if args.preflight:
            reporter.emit("complete", 100, "Preflight concluido sem alteracoes")
            print("PREFLIGHT CONCLUIDO: nenhuma transferencia ou reinicializacao foi executada.")
            print(f"Modelo detectado: Aruba {detected_model}")
            print(f"WebUI sysName: {initial_identity.sys_name}")
            print(f"WebUI sysDescr: {initial_identity.sys_descr}")
            print(f"Versao na WebUI: {initial_web_version or 'nao localizada'}")
            return

        if args.wizard_check:
            reporter.emit("upload_setup", 30, "Validando o assistente sem anexar firmware")
            updater.open_update_wizard()
            updater.validate_upload_field()
            reporter.emit("complete", 100, "Assistente validado sem upload ou reinicializacao")
            print("WIZARD CHECK CONCLUIDO: o campo de arquivo foi alcançado sem anexar firmware.")
            print("Nenhuma transferencia ou reinicializacao foi executada.")
            return

        if args.save_check:
            reporter.emit("saving", 95, "Salvando a configuracao pendente no switch")
            changed = updater.save_configuration()
            if changed:
                reporter.emit("complete", 100, "Configuracao salva e persistencia confirmada")
                print("SAVE CHECK CONCLUIDO: a configuracao pendente foi salva.")
            else:
                reporter.emit("complete", 100, "WebUI sem alteracoes pendentes para salvar")
                print("SAVE CHECK CONCLUIDO: nao havia configuracao pendente.")
            print("Nenhum upload ou reinicializacao foi executado.")
            return

        confirm_execution(args, firmware, expected_version, same_version, downgrade)

        reporter.emit("upload_setup", 30, "Abrindo assistente e anexando firmware")
        updater.open_update_wizard()
        updater.attach_firmware(firmware)
        updater.start_transfer_and_wait(
            args.transfer_timeout,
            reporter,
            stall_timeout=args.transfer_stall_timeout,
        )
        reporter.emit("restart", 65, "Transferencia concluida; reiniciando switch")
        updater.restart()

        wait_for_ping_after_restart(host, args.reboot_timeout, reporter=reporter)

        reporter.emit("verifying_web", 85, "Aguardando WebUI e consultando versao final")
        wait_for_web_identity(
            url,
            args.http_timeout,
            args.insecure_tls,
        )
        updater.login()
        final_identity = fetch_web_identity(url, args.http_timeout, args.insecure_tls)
        final_web_version = updater.read_web_version()
        confirmed_release = release_version(expected_version)
        LOGGER.info("Versao final HTTP direto: %s", final_identity.sys_descr)
        LOGGER.info("Versao final WebUI: %s", final_web_version or "nao localizada")

        if final_identity.model != expected_model:
            raise UpdateError(
                f"O switch retornou como Aruba {final_identity.model or 'desconhecido'}, "
                f"mas era esperado Aruba {expected_model}."
            )
        if not final_version_matches(expected_version, final_identity.sys_descr):
            raise UpdateError(
                "O switch retornou, mas a versao publica da WebUI nao corresponde a esperada: "
                f"esperada={confirmed_release!r}, obtida={final_identity.sys_descr!r}."
            )
        if final_web_version and not final_version_matches(expected_version, final_web_version):
            raise UpdateError(
                "A versao autenticada da WebUI diverge da versao esperada: "
                f"esperada={confirmed_release!r}, obtida={final_web_version!r}."
            )
        reporter.emit("saving", 95, "Versao confirmada; salvando a configuracao no switch")
        saved_configuration = updater.save_configuration(pending_timeout=90)
        if not saved_configuration:
            LOGGER.info(
                "O botao Save Configuration nao apareceu em ate 90 segundos; "
                "a versao ja foi confirmada e o processo sera concluido sem erro."
            )
        LOGGER.info("Versao final confirmada: %s.", confirmed_release)
        reporter.emit(
            "complete",
            100,
            f"Versao final {confirmed_release} confirmada; processo concluido",
        )
        action = "reinstalado" if same_version else "rebaixado" if downgrade else "atualizado"
        print(
            f"SUCESSO: Aruba {detected_model} {action} com a versao {confirmed_release}. "
            "O resultado pode ser salvo no Sentinel."
        )
    except Exception as exc:
        failure_message = concise_exception_message(exc)
        if isinstance(exc, UpdateNeedsReview):
            reporter.emit("needs_review", reporter.last_percent, failure_message)
        else:
            reporter.fail(failure_message)
        if updater and args.capture_diagnostics:
            updater.capture_diagnostics(failure_message)
        raise
    finally:
        if updater:
            updater.close()


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    try:
        run(args)
    except UpdateError as exc:
        LOGGER.error("%s", exc)
        return 2
    except KeyboardInterrupt:
        LOGGER.error("Execucao interrompida pelo usuario.")
        return 130
    except Exception:
        LOGGER.exception("Falha inesperada na alpha.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
