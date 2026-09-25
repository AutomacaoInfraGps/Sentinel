"""Protecao temporaria contra suspensao durante atualizacoes de switches."""

from __future__ import annotations

from contextlib import contextmanager
import ctypes
import logging
import os
from typing import Iterator


LOGGER = logging.getLogger("sentinel.switch-update.power")

# Mantem o sistema ativo, mas permite que a tela seja bloqueada ou desligada.
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_CONTINUOUS = 0x80000000


class PowerRequestError(RuntimeError):
    """O Windows recusou a solicitacao para manter o sistema acordado."""


@contextmanager
def keep_system_awake() -> Iterator[None]:
    """Impede suspensao automatica enquanto o bloco estiver em execucao.

    A solicitacao pertence a thread e e removida no ``finally``. O monitor nao
    e mantido ligado, portanto bloquear a tela nao interfere no processo.
    """
    if os.name != "nt":
        yield
        return

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetThreadExecutionState.argtypes = (ctypes.c_uint32,)
    kernel32.SetThreadExecutionState.restype = ctypes.c_uint32

    flags = _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED
    if not kernel32.SetThreadExecutionState(flags):
        raise PowerRequestError(
            "O Windows nao permitiu impedir a suspensao automatica "
            f"(erro {ctypes.get_last_error()})."
        )

    LOGGER.info(
        "Protecao de energia ativa: suspensao automatica bloqueada; "
        "bloqueio e desligamento da tela permanecem permitidos."
    )
    try:
        yield
    finally:
        if not kernel32.SetThreadExecutionState(_ES_CONTINUOUS):
            LOGGER.error(
                "O Windows nao confirmou a remocao da protecao de energia "
                "(erro %s).",
                ctypes.get_last_error(),
            )
        else:
            LOGGER.info("Protecao de energia removida ao finalizar o worker.")
