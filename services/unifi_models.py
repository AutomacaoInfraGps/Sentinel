"""Nomes de exibicao para os codigos de modelo retornados pela UniFi."""


UNIFI_MODEL_NAMES = {
    "UAL6": "U6 LITE",
    "U7PG2": "AC PRO",
    "U7HD": "AC HD",
    "UALR6V2": "U6 LR",
    "UAP6MP": "U6 PRO",
    "U7LR": "AC LR",
    "U7MP": "AC Mesh PRO",
    "U6MP": "U6 Mesh PRO",
    "U7LT": "AC LITE",
    "BZ2LR": "UAP LR",
    "BZ2": "UAP",
    "U7PRO": "U7 PRO",
    "U7PROMAX": "U7 PRO MAX",
    "UKPW": "U7 Outdoor",
    "UAPA693": "U7 Lite",
    "U7SHD": "AC SHD",
}


def nome_modelo_unifi(codigo):
    """Retorna o nome conhecido ou preserva o codigo informado."""
    valor = str(codigo or "").strip()
    return UNIFI_MODEL_NAMES.get(valor.upper(), valor)


def normalizar_modelo_ap(ap):
    """Copia um registro de AP e aplica o nome amigavel para exibicao."""
    registro = dict(ap or {})
    codigo = registro.get("modelo_codigo") or registro.get("model") or registro.get("modelo")
    registro["modelo"] = nome_modelo_unifi(codigo)
    return registro
