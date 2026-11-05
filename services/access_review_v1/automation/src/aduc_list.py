"""Seleciona um grupo na lista nativa do ADUC via Win32, sem alterar o AD."""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LVM_FINDITEMW = 0x1053
LVM_GETITEMCOUNT = 0x1004
LVM_SETITEMSTATE = 0x102B
LVM_ENSUREVISIBLE = 0x1013
LVM_GETITEMTEXTW = 0x1073
LVM_GETITEMRECT = 0x100E
LVM_SCROLL = 0x1014
LVFI_STRING = 0x0002
LVFI_PARTIAL = 0x0008
LVIS_FOCUSED = 0x0001
LVIS_SELECTED = 0x0002
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class LVFINDINFOW(ctypes.Structure):
    _fields_ = [
        ("flags", wintypes.UINT),
        ("psz", ctypes.c_void_p),
        ("lParam", ctypes.c_ssize_t),
        ("pt", POINT),
        ("vkDirection", wintypes.UINT),
    ]


class LVITEMW(ctypes.Structure):
    _fields_ = [
        ("mask", wintypes.UINT),
        ("iItem", ctypes.c_int),
        ("iSubItem", ctypes.c_int),
        ("state", wintypes.UINT),
        ("stateMask", wintypes.UINT),
        ("pszText", ctypes.c_void_p),
        ("cchTextMax", ctypes.c_int),
        ("iImage", ctypes.c_int),
        ("lParam", ctypes.c_ssize_t),
        ("iIndent", ctypes.c_int),
        ("iGroupId", ctypes.c_int),
        ("cColumns", wintypes.UINT),
        ("puColumns", ctypes.c_void_p),
        ("piColFmt", ctypes.c_void_p),
        ("iGroup", ctypes.c_int),
    ]


kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
kernel32.VirtualAllocEx.restype = ctypes.c_void_p
kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.restype = wintypes.BOOL
kernel32.VirtualFreeEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]
kernel32.VirtualFreeEx.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.ReadProcessMemory.restype = wintypes.BOOL
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
user32.ClientToScreen.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetClientRect.restype = wintypes.BOOL
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.SetFocus.argtypes = [wintypes.HWND]
user32.SetFocus.restype = wintypes.HWND
user32.GetFocus.restype = wintypes.HWND
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]


def check(value, label: str):
    if not value:
        raise OSError(ctypes.get_last_error(), label)
    return value


def select_index(process, remote: int, list_hwnd: int, index: int, label: str) -> None:
    """Seleciona uma linha conhecida quando a lista do MMC não expõe seu texto."""
    total = user32.SendMessageW(list_hwnd, LVM_GETITEMCOUNT, 0, 0)
    if index < 0 or index >= total:
        raise IndexError(f"Índice {index} inválido para a lista com {total} itens")

    written = ctypes.c_size_t()
    state = LVITEMW()
    state.state = 0
    state.stateMask = LVIS_SELECTED | LVIS_FOCUSED
    check(
        kernel32.WriteProcessMemory(process, remote, ctypes.byref(state), ctypes.sizeof(state), ctypes.byref(written)),
        "WriteProcessMemory(clear state)",
    )
    user32.SendMessageW(list_hwnd, LVM_SETITEMSTATE, ctypes.c_size_t(-1).value, remote)
    state.state = LVIS_SELECTED | LVIS_FOCUSED
    check(
        kernel32.WriteProcessMemory(process, remote, ctypes.byref(state), ctypes.sizeof(state), ctypes.byref(written)),
        "WriteProcessMemory(state)",
    )
    check(user32.SendMessageW(list_hwnd, LVM_SETITEMSTATE, index, remote), "LVM_SETITEMSTATE")
    user32.SendMessageW(list_hwnd, LVM_ENSUREVISIBLE, index, 0)

    target_pid = wintypes.DWORD()
    target_thread = user32.GetWindowThreadProcessId(list_hwnd, ctypes.byref(target_pid))
    own_thread = kernel32.GetCurrentThreadId()
    check(user32.AttachThreadInput(own_thread, target_thread, True), "AttachThreadInput")
    try:
        user32.SetFocus(list_hwnd)
        if user32.GetFocus() != list_hwnd:
            print("Aviso: foco da lista não confirmado; seleção mantida")
    finally:
        user32.AttachThreadInput(own_thread, target_thread, False)
    print(f"Itens na lista: {total}; linha {index + 1} selecionada para {label}")


def select_subitem(process, remote: int, list_hwnd: int, text: str, column: int, occurrence: int) -> None:
    """Seleciona uma linha pelo texto de uma coluna diferente da coluna principal."""
    if column < 1:
        raise ValueError("A coluna secundária deve ser positiva")
    if occurrence < 1:
        raise ValueError("--occurrence deve ser positivo")
    written = ctypes.c_size_t()
    total = user32.SendMessageW(list_hwnd, LVM_GETITEMCOUNT, 0, 0)
    matches: list[tuple[int, str]] = []
    for index in range(total):
        item = LVITEMW()
        item.iSubItem = column
        item.pszText = remote + 256
        item.cchTextMax = 1000
        check(kernel32.WriteProcessMemory(process, remote, ctypes.byref(item), ctypes.sizeof(item), ctypes.byref(written)), "WriteProcessMemory(item)")
        user32.SendMessageW(list_hwnd, LVM_GETITEMTEXTW, index, remote)
        buffer = (ctypes.c_ubyte * 2000)()
        check(kernel32.ReadProcessMemory(process, remote + 256, buffer, 2000, ctypes.byref(written)), "ReadProcessMemory(item)")
        actual = bytes(buffer).decode("utf-16-le", errors="ignore").split("\0", 1)[0]
        if actual.casefold().startswith(text.casefold()):
            matches.append((index, actual))
    if len(matches) < occurrence:
        raise RuntimeError(f"Texto {text!r} não encontrado na coluna {column}; correspondências: {len(matches)}")
    index, actual = matches[occurrence - 1]

    state = LVITEMW()
    state.state = 0
    state.stateMask = LVIS_SELECTED | LVIS_FOCUSED
    check(kernel32.WriteProcessMemory(process, remote, ctypes.byref(state), ctypes.sizeof(state), ctypes.byref(written)), "WriteProcessMemory(clear state)")
    user32.SendMessageW(list_hwnd, LVM_SETITEMSTATE, ctypes.c_size_t(-1).value, remote)
    state.state = LVIS_SELECTED | LVIS_FOCUSED
    check(kernel32.WriteProcessMemory(process, remote, ctypes.byref(state), ctypes.sizeof(state), ctypes.byref(written)), "WriteProcessMemory(state)")
    check(user32.SendMessageW(list_hwnd, LVM_SETITEMSTATE, index, remote), "LVM_SETITEMSTATE")
    user32.SendMessageW(list_hwnd, LVM_ENSUREVISIBLE, index, 0)
    target_pid = wintypes.DWORD()
    target_thread = user32.GetWindowThreadProcessId(list_hwnd, ctypes.byref(target_pid))
    own_thread = kernel32.GetCurrentThreadId()
    check(user32.AttachThreadInput(own_thread, target_thread, True), "AttachThreadInput")
    try:
        user32.SetFocus(list_hwnd)
        if user32.GetFocus() != list_hwnd:
            print("Aviso: foco da lista não confirmado; seleção mantida")
    finally:
        user32.AttachThreadInput(own_thread, target_thread, False)
    print(f"Linha selecionada pela coluna {column}: {actual}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pid", type=int)
    parser.add_argument("list_hwnd", type=int)
    parser.add_argument("group")
    parser.add_argument("--main-hwnd", type=int)
    parser.add_argument("--open-properties", action="store_true")
    parser.add_argument("--partial", action="store_true", help="Seleciona a primeira entrada cujo nome começa com o texto")
    parser.add_argument("--occurrence", type=int, default=1)
    parser.add_argument("--column", type=int, default=0)
    parser.add_argument("--index", type=int, help="Seleciona diretamente um índice baseado em zero")
    args = parser.parse_args()
    process = check(kernel32.OpenProcess(PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE, False, args.pid), "OpenProcess")
    remote = check(kernel32.VirtualAllocEx(process, None, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE), "VirtualAllocEx")
    try:
        if args.index is not None:
            if args.open_properties or args.column:
                raise ValueError("--index não é compatível com --open-properties ou --column")
            select_index(process, remote, args.list_hwnd, args.index, args.group)
            return
        if args.column:
            if args.open_properties:
                raise ValueError("--open-properties não é compatível com --column")
            select_subitem(process, remote, args.list_hwnd, args.group, args.column, args.occurrence)
            return
        name = ctypes.create_unicode_buffer(args.group)
        count = ctypes.c_size_t()
        check(kernel32.WriteProcessMemory(process, remote + 256, name, ctypes.sizeof(name), ctypes.byref(count)), "WriteProcessMemory(name)")
        query = LVFINDINFOW()
        query.flags = LVFI_STRING | (LVFI_PARTIAL if args.partial else 0)
        query.psz = remote + 256
        check(kernel32.WriteProcessMemory(process, remote, ctypes.byref(query), ctypes.sizeof(query), ctypes.byref(count)), "WriteProcessMemory(query)")
        total = user32.SendMessageW(args.list_hwnd, LVM_GETITEMCOUNT, 0, 0)
        if args.occurrence < 1:
            raise ValueError("--occurrence deve ser positivo")
        index = -1
        for _ in range(args.occurrence):
            index = user32.SendMessageW(args.list_hwnd, LVM_FINDITEMW, ctypes.c_size_t(index).value, remote)
            if index < 0:
                break
        print(f"Itens na lista: {total}; índice de {args.group}: {index}")
        if index < 0:
            raise SystemExit("Grupo não localizado na lista visível do ADUC")
        item_text = LVITEMW()
        item_text.iSubItem = 0
        item_text.pszText = remote + 256
        item_text.cchTextMax = 1000
        check(kernel32.WriteProcessMemory(process, remote, ctypes.byref(item_text), ctypes.sizeof(item_text), ctypes.byref(count)), "WriteProcessMemory(item text)")
        user32.SendMessageW(args.list_hwnd, LVM_GETITEMTEXTW, index, remote)
        text_buffer = (ctypes.c_ubyte * 2000)()
        check(kernel32.ReadProcessMemory(process, remote + 256, text_buffer, 2000, ctypes.byref(count)), "ReadProcessMemory(item text)")
        actual_name = bytes(text_buffer).decode("utf-16-le", errors="ignore").split("\0", 1)[0]
        name_ok = actual_name.casefold().startswith(args.group.casefold()) if args.partial else actual_name.casefold() == args.group.casefold()
        if not name_ok:
            raise RuntimeError(f"O ADUC selecionou {actual_name!r}, esperado {args.group!r}")
        state = LVITEMW()
        state.state = 0
        state.stateMask = LVIS_SELECTED | LVIS_FOCUSED
        check(kernel32.WriteProcessMemory(process, remote, ctypes.byref(state), ctypes.sizeof(state), ctypes.byref(count)), "WriteProcessMemory(clear state)")
        user32.SendMessageW(args.list_hwnd, LVM_SETITEMSTATE, ctypes.c_size_t(-1).value, remote)
        state.state = LVIS_SELECTED | LVIS_FOCUSED
        state.stateMask = LVIS_SELECTED | LVIS_FOCUSED
        check(kernel32.WriteProcessMemory(process, remote, ctypes.byref(state), ctypes.sizeof(state), ctypes.byref(count)), "WriteProcessMemory(state)")
        result = user32.SendMessageW(args.list_hwnd, LVM_SETITEMSTATE, index, remote)
        check(result, "LVM_SETITEMSTATE")
        visible = user32.SendMessageW(args.list_hwnd, LVM_ENSUREVISIBLE, index, 0)
        print(f"Grupo selecionado no ADUC; item rolado para a área visível: {bool(visible)}")
        rect = RECT()
        check(kernel32.WriteProcessMemory(process, remote, ctypes.byref(rect), ctypes.sizeof(rect), ctypes.byref(count)), "WriteProcessMemory(rect)")
        check(user32.SendMessageW(args.list_hwnd, LVM_GETITEMRECT, index, remote), "LVM_GETITEMRECT")
        check(kernel32.ReadProcessMemory(process, remote, ctypes.byref(rect), ctypes.sizeof(rect), ctypes.byref(count)), "ReadProcessMemory(rect)")
        client = RECT()
        check(user32.GetClientRect(args.list_hwnd, ctypes.byref(client)), "GetClientRect")
        offset = ((rect.top + rect.bottom) // 2) - (client.bottom // 2)
        if offset > 0:
            user32.SendMessageW(args.list_hwnd, LVM_SCROLL, 0, offset)
        if args.main_hwnd:
            user32.SetForegroundWindow(args.main_hwnd)
        target_pid = wintypes.DWORD()
        target_thread = user32.GetWindowThreadProcessId(args.list_hwnd, ctypes.byref(target_pid))
        own_thread = kernel32.GetCurrentThreadId()
        check(user32.AttachThreadInput(own_thread, target_thread, True), "AttachThreadInput")
        try:
            user32.SetFocus(args.list_hwnd)
            if user32.GetFocus() != args.list_hwnd:
                print("Aviso: foco da lista não confirmado; continuando pelo item selecionado")
        finally:
            user32.AttachThreadInput(own_thread, target_thread, False)
        if args.open_properties:
            if not args.main_hwnd:
                raise ValueError("--main-hwnd é obrigatório para abrir propriedades")
            rect = RECT()
            check(kernel32.WriteProcessMemory(process, remote, ctypes.byref(rect), ctypes.sizeof(rect), ctypes.byref(count)), "WriteProcessMemory(rect)")
            check(user32.SendMessageW(args.list_hwnd, LVM_GETITEMRECT, index, remote), "LVM_GETITEMRECT")
            check(kernel32.ReadProcessMemory(process, remote, ctypes.byref(rect), ctypes.sizeof(rect), ctypes.byref(count)), "ReadProcessMemory(rect)")
            point = POINT(rect.left + 75, (rect.top + rect.bottom) // 2)
            check(user32.ClientToScreen(args.list_hwnd, ctypes.byref(point)), "ClientToScreen")
            # SetForegroundWindow pode retornar zero mesmo quando o ADUC já está
            # em primeiro plano. A confirmação confiável é o PID da janela ativa,
            # verificado logo abaixo.
            if not user32.SetForegroundWindow(args.main_hwnd):
                print("Aviso: Windows não confirmou SetForegroundWindow; validando pelo PID ativo")
            foreground = user32.GetForegroundWindow()
            foreground_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(foreground, ctypes.byref(foreground_pid))
            if foreground_pid.value != args.pid:
                raise RuntimeError(f"ADUC não está em primeiro plano; foco no PID {foreground_pid.value}")
            check(user32.SetCursorPos(point.x, point.y), "SetCursorPos")
            for _ in range(2):
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                user32.mouse_event(0x0004, 0, 0, 0, 0)
            print(f"Propriedades solicitadas por duplo clique em {point.x},{point.y}")
    finally:
        kernel32.VirtualFreeEx(process, remote, 0, MEM_RELEASE)
        kernel32.CloseHandle(process)


if __name__ == "__main__":
    main()
