"""Inspeciona a árvore nativa do ADUC por mensagens Win32 (somente leitura)."""

from __future__ import annotations

import argparse
import ctypes
import struct
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04
TVM_GETNEXTITEM = 0x110A
TVM_GETITEMW = 0x113E
TVM_SELECTITEM = 0x110B
TVM_EXPAND = 0x1102
TVM_GETITEMRECT = 0x1104
TVGN_ROOT = 0
TVGN_NEXT = 1
TVGN_CHILD = 4
TVGN_CARET = 9
TVE_EXPAND = 2
TVIF_TEXT = 1


class TVITEMW(ctypes.Structure):
    _fields_ = [
        ("mask", wintypes.UINT),
        ("hItem", ctypes.c_void_p),
        ("state", wintypes.UINT),
        ("stateMask", wintypes.UINT),
        ("pszText", ctypes.c_void_p),
        ("cchTextMax", ctypes.c_int),
        ("iImage", ctypes.c_int),
        ("iSelectedImage", ctypes.c_int),
        ("cChildren", ctypes.c_int),
        ("lParam", ctypes.c_ssize_t),
    ]


kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
kernel32.VirtualAllocEx.restype = ctypes.c_void_p
kernel32.VirtualFreeEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]
kernel32.VirtualFreeEx.restype = wintypes.BOOL
kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.restype = wintypes.BOOL
kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.ReadProcessMemory.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.ClientToScreen.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.SwitchToThisWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.SetFocus.argtypes = [wintypes.HWND]
user32.SetFocus.restype = wintypes.HWND
user32.GetFocus.restype = wintypes.HWND
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ctypes.c_size_t]
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
user32.SendMessageW.restype = ctypes.c_ssize_t


def check(ok: object, label: str) -> None:
    if not ok:
        raise OSError(ctypes.get_last_error(), label)


def read_bytes(process: int, address: int, size: int) -> bytes:
    buffer = (ctypes.c_ubyte * size)()
    count = ctypes.c_size_t()
    check(kernel32.ReadProcessMemory(process, address, buffer, size, ctypes.byref(count)), "ReadProcessMemory")
    return bytes(buffer[: count.value])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pid", type=int)
    parser.add_argument("tree_hwnd", type=int)
    parser.add_argument("--select")
    parser.add_argument("--main-hwnd", type=int)
    parser.add_argument("--open-properties", action="store_true")
    args = parser.parse_args()
    process = kernel32.OpenProcess(PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE, False, args.pid)
    check(process, "OpenProcess")
    remote = kernel32.VirtualAllocEx(process, None, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
    check(remote, "VirtualAllocEx")
    try:
        def get_text(item_handle: int) -> str:
            text_pointer = remote + 256
            request = TVITEMW()
            request.mask = TVIF_TEXT
            request.hItem = item_handle
            request.pszText = text_pointer
            request.cchTextMax = 1000
            count = ctypes.c_size_t()
            check(kernel32.WriteProcessMemory(process, remote, ctypes.byref(request), ctypes.sizeof(request), ctypes.byref(count)), "WriteProcessMemory")
            result = user32.SendMessageW(args.tree_hwnd, TVM_GETITEMW, 0, remote)
            check(result, "TVM_GETITEMW")
            return read_bytes(process, text_pointer, 2000).decode("utf-16-le", errors="ignore").split("\0", 1)[0]

        def children(parent: int):
            item = user32.SendMessageW(args.tree_hwnd, TVM_GETNEXTITEM, TVGN_ROOT if not parent else TVGN_CHILD, parent)
            count = 0
            while item and count < 300:
                yield item
                item = user32.SendMessageW(args.tree_hwnd, TVM_GETNEXTITEM, TVGN_NEXT, item)
                count += 1

        def walk(parent: int, level: int = 0) -> None:
            if level > 5:
                return
            for item in children(parent):
                print("  " * level + f"{item}: {get_text(item)}")
                walk(item, level + 1)

        if args.select:
            parent = 0
            for name in args.select.split("/"):
                if parent:
                    user32.SendMessageW(args.tree_hwnd, TVM_EXPAND, TVE_EXPAND, parent)
                    time.sleep(0.4)
                matches = [item for item in children(parent) if get_text(item).casefold() == name.casefold()]
                if not matches and not parent:
                    roots = list(children(0))
                    if len(roots) == 1:
                        parent = roots[0]
                        user32.SendMessageW(args.tree_hwnd, TVM_EXPAND, TVE_EXPAND, parent)
                        time.sleep(0.4)
                        matches = [item for item in children(parent) if get_text(item).casefold() == name.casefold()]
                if len(matches) != 1:
                    raise RuntimeError(f"Nó {name!r} não encontrado de forma única; encontrados: {len(matches)}")
                parent = matches[0]
                print(f"Nó localizado: {name} ({parent})")
            result = user32.SendMessageW(args.tree_hwnd, TVM_SELECTITEM, TVGN_CARET, parent)
            check(result, "TVM_SELECTITEM")
            print(f"OU selecionada: {get_text(parent)}")
            if args.open_properties:
                if not args.main_hwnd:
                    raise ValueError("--main-hwnd é obrigatório para abrir propriedades")
                handle_bytes = struct.pack("<Q", parent)
                input_buffer = ctypes.create_string_buffer(handle_bytes)
                count = ctypes.c_size_t()
                check(kernel32.WriteProcessMemory(process, remote, input_buffer, len(handle_bytes), ctypes.byref(count)), "WriteProcessMemory(rect)")
                check(user32.SendMessageW(args.tree_hwnd, TVM_GETITEMRECT, 1, remote), "TVM_GETITEMRECT")
                left, top, right, bottom = struct.unpack("<iiii", read_bytes(process, remote, 16))
                point = (ctypes.c_long * 2)(left + 25, (top + bottom) // 2)
                check(user32.ClientToScreen(args.tree_hwnd, ctypes.byref(point)), "ClientToScreen")
                user32.keybd_event(0x12, 0, 0, 0)
                user32.keybd_event(0x12, 0, 0x0002, 0)
                user32.SetForegroundWindow(args.main_hwnd)
                time.sleep(0.2)
                foreground = user32.GetForegroundWindow()
                foreground_pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(foreground, ctypes.byref(foreground_pid))
                if foreground_pid.value != args.pid:
                    user32.SwitchToThisWindow(args.main_hwnd, True)
                    time.sleep(0.2)
                    foreground = user32.GetForegroundWindow()
                    user32.GetWindowThreadProcessId(foreground, ctypes.byref(foreground_pid))
                if foreground_pid.value != args.pid:
                    raise RuntimeError(f"ADUC não está em primeiro plano; foco no PID {foreground_pid.value}")
                check(user32.SetCursorPos(point[0], point[1]), "SetCursorPos")
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                time.sleep(0.2)
                tree_pid = wintypes.DWORD()
                tree_thread = user32.GetWindowThreadProcessId(args.tree_hwnd, ctypes.byref(tree_pid))
                current_thread = kernel32.GetCurrentThreadId()
                check(user32.AttachThreadInput(current_thread, tree_thread, True), "AttachThreadInput")
                try:
                    user32.SetFocus(args.tree_hwnd)
                    if user32.GetFocus() != args.tree_hwnd:
                        print("Aviso: foco da árvore não confirmado; continuando pelo item selecionado")
                finally:
                    user32.AttachThreadInput(current_thread, tree_thread, False)
                user32.keybd_event(0x12, 0, 0, 0)
                user32.keybd_event(0x0D, 0, 0, 0)
                user32.keybd_event(0x0D, 0, 0x0002, 0)
                user32.keybd_event(0x12, 0, 0x0002, 0)
                print(f"Propriedades da OU solicitadas em {point[0]},{point[1]}")
        else:
            walk(0)
    finally:
        kernel32.VirtualFreeEx(process, remote, 0, MEM_RELEASE)
        kernel32.CloseHandle(process)


if __name__ == "__main__":
    main()
