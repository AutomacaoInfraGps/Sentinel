"""Localiza janelas e controles nativos de uma instância do ADUC."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
CALLBACK = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [CALLBACK, wintypes.LPARAM]
user32.EnumChildWindows.argtypes = [wintypes.HWND, CALLBACK, wintypes.LPARAM]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL]
user32.MoveWindow.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.GetWindowRect.restype = wintypes.BOOL
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
user32.GetMonitorInfoW.restype = wintypes.BOOL


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]


def describe(hwnd: int) -> dict:
    title = ctypes.create_unicode_buffer(512)
    cls = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title, len(title))
    user32.GetClassNameW(hwnd, cls, len(cls))
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return {"hwnd": int(hwnd), "title": title.value, "class": cls.value, "pid": pid.value}


def top_windows(pid: int) -> list[dict]:
    found = []

    @CALLBACK
    def callback(hwnd, _):
        item = describe(hwnd)
        if item["pid"] == pid and user32.IsWindowVisible(hwnd):
            found.append(item)
        return True

    user32.EnumWindows(callback, 0)
    return found


def all_top_windows() -> list[dict]:
    found = []

    @CALLBACK
    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            found.append(describe(hwnd))
        return True

    user32.EnumWindows(callback, 0)
    return found


def children(hwnd: int) -> list[dict]:
    found = []

    @CALLBACK
    def callback(child, _):
        found.append(describe(child))
        return True

    user32.EnumChildWindows(hwnd, callback, 0)
    return found


def only(items: list[dict], *, cls: str | None = None, title: str | None = None) -> dict:
    matching = [x for x in items if (cls is None or x["class"] == cls) and (title is None or x["title"] == title)]
    if len(matching) != 1:
        raise RuntimeError(f"Esperado um controle {cls!r}/{title!r}; encontrados: {matching}")
    return matching[0]


def close_dialog(hwnd: int) -> None:
    user32.PostMessageW(hwnd, 0x0010, 0, 0)


def stretch_security_dialog(hwnd: int, main_hwnd: int) -> tuple[int, int]:
    """Amplia o ADUC e seu diálogo de segurança na área útil do monitor."""
    monitor = user32.MonitorFromWindow(main_hwnd, 2)
    if not monitor:
        raise OSError(ctypes.get_last_error(), "MonitorFromWindow")
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(info)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        raise OSError(ctypes.get_last_error(), "GetMonitorInfoW")
    work = info.rcWork
    user32.ShowWindow(main_hwnd, 3)
    width = min(work.right - work.left - 40, 1180)
    height = work.bottom - work.top - 32
    x = work.left + (work.right - work.left - width) // 2
    y = work.top + 8
    if not user32.MoveWindow(hwnd, x, y, width, height, True):
        raise OSError(ctypes.get_last_error(), "MoveWindow")
    return width, height


def click_tab(tab_hwnd: int, x: int, y: int) -> None:
    packed = (y << 16) | (x & 0xFFFF)
    user32.SendMessageW(tab_hwnd, 0x0201, 1, packed)
    user32.SendMessageW(tab_hwnd, 0x0202, 0, packed)


def click_button(button_hwnd: int) -> None:
    # BM_CLICK precisa ser assíncrono: alguns botões abrem uma caixa modal e o
    # SendMessage só retornaria depois que ela fosse fechada pelo próprio bot.
    user32.PostMessageW(button_hwnd, 0x00F5, 0, 0)
