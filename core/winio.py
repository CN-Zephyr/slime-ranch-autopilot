# -*- coding: utf-8 -*-
"""Win32 真实控制层：附加游戏窗口、窗口 rect、后台截屏、SendInput 键鼠。

只用标准库 ctypes 调 Windows API —— 这样在 NEKO 内置的 Python 里也能跑，
无需安装 mss / pyautogui。截屏默认走 GDI BitBlt（纯 ctypes，无依赖）；若导入
了 mss 则优先用 mss（更快、带 BGR 转 RGB）。本模块仅支持 Windows。
"""
from __future__ import annotations

import os
import sys
import time
import ctypes
from ctypes import wintypes
from typing import List, Mapping, Optional, Tuple

from PIL import Image

if sys.platform != "win32":
    raise ImportError("winio 仅支持 Windows")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32  # BitBlt/CreateCompatibleDC 等 GDI 绘制函数属于 gdi32

# ------------------------------------------------------------------ 基础常量
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_ABSOLUTE = 0x8000

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

# 常见键名 -> (虚拟键码, 扫描码)
_KEY_MAP: Mapping[str, Tuple[int, int]] = {
    "esc": (0x1B, 0x01), "enter": (0x0D, 0x1C), "return": (0x0D, 0x1C),
    "tab": (0x09, 0x0F), "space": (0x20, 0x39),
    "up": (0x26, 0x48), "down": (0x28, 0x50), "left": (0x25, 0x4B), "right": (0x27, 0x4D),
    "home": (0x24, 0x47), "end": (0x23, 0x4F),
    "m": (0x4D, 0x32), "e": (0x45, 0x12), "u": (0x55, 0x16), "w": (0x57, 0x11),
    "a": (0x41, 0x1E), "s": (0x53, 0x1F), "d": (0x44, 0x20),
    "shift": (0x10, 0x2A), "lshift": (0x10, 0x2A), "ctrl": (0x11, 0x1D),
    "1": (0x31, 0x02), "2": (0x32, 0x03), "3": (0x33, 0x04),
}


# ------------------------------------------------------------------ INPUT 结构
class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


def _send_input(*inputs: _INPUT) -> bool:
    n = len(inputs)
    arr = (_INPUT * n)(*inputs)
    return bool(user32.SendInput(n, arr, ctypes.sizeof(_INPUT)))


def _mk_mouse(dx: int, dy: int, flags: int) -> _INPUT:
    return _INPUT(INPUT_MOUSE, _INPUTUNION(mi=_MOUSEINPUT(dx, dy, 0, flags, 0, None)))


def _mk_key(vk: int, scan: int, flags: int) -> _INPUT:
    return _INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=_KEYBDINPUT(vk, scan, flags, 0, None)))


# ------------------------------------------------------------------ 鼠标
def _screen_clamp(v: int) -> int:
    return max(0, min(65535, v))


def mouse_move_to(x: int, y: int) -> None:
    """绝对坐标移动（用 ABSOLUTE 归一化范围 0..65535）。"""
    sw = user32.GetSystemMetrics(0) or 1
    sh = user32.GetSystemMetrics(1) or 1
    _send_input(_mk_mouse(_screen_clamp(x * 65535 // sw), _screen_clamp(y * 65535 // sh),
                          MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE))


def mouse_move_rel(dx: int, dy: int) -> None:
    """相对移动（像素增量，不带 ABSOLUTE）。用于真实转动 FPS/TPS 视角：
    只产生沿窗口中心的位移，光标可被游戏锁定在中央，适合第三人称视角旋转。
    """
    _send_input(_mk_mouse(dx, dy, MOUSEEVENTF_MOVE))


def mouse_click(x: int, y: int, button: str = "left") -> None:
    mouse_move_to(x, y)
    time.sleep(0.05)
    if button == "right":
        down, up = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
    else:
        down, up = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
    _send_input(_mk_mouse(0, 0, down))
    time.sleep(0.05)
    _send_input(_mk_mouse(0, 0, up))


def mouse_hold(x: int, y: int, seconds: float, button: str = "left") -> None:
    mouse_move_to(x, y)
    time.sleep(0.05)
    down, up = (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP) if button == "right" else \
        (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
    _send_input(_mk_mouse(0, 0, down))
    time.sleep(seconds)
    _send_input(_mk_mouse(0, 0, up))


# ------------------------------------------------------------------ 键盘
def key_down(key: str) -> None:
    vk, scan = _KEY_MAP.get(key.lower(), _key_of(key))
    _send_input(_mk_key(vk, scan, 0))


def key_up(key: str) -> None:
    vk, scan = _KEY_MAP.get(key.lower(), _key_of(key))
    _send_input(_mk_key(vk, scan, KEYEVENTF_KEYUP))


def press_key(key: str) -> None:
    vk, scan = _KEY_MAP.get(key.lower(), _key_of(key))
    _send_input(_mk_key(vk, scan, 0), _mk_key(vk, scan, KEYEVENTF_KEYUP))


def key_hold(key: str, seconds: float) -> None:
    vk, scan = _KEY_MAP.get(key.lower(), _key_of(key))
    _send_input(_mk_key(vk, scan, 0))
    time.sleep(seconds)
    _send_input(_mk_key(vk, scan, KEYEVENTF_KEYUP))


def keys_hold(keys, seconds: float) -> None:
    """同时按住多个键(如 ["w","shift"] 跑步前进)再一起松开。"""
    pairs = []
    for k in keys:
        k = k.lower()
        if k not in _KEY_MAP:
            continue
        vk, scan = _KEY_MAP[k]
        pairs.append((vk, scan))
    for vk, scan in pairs:
        _send_input(_mk_key(vk, scan, 0))
    time.sleep(seconds)
    for vk, scan in reversed(pairs):
        _send_input(_mk_key(vk, scan, KEYEVENTF_KEYUP))


def _key_of(key: str) -> Tuple[int, int]:
    k = key.upper()
    if len(k) == 1:
        return (ord(k), 0)  # A-Z 0-9 与 VK 等价
    return (0, 0)


# ------------------------------------------------------------------ 窗口
def find_game_window(exe_name: str = "SlimeRancher.exe") -> Optional[int]:
    """按进程可执行文件名查主窗口句柄。返回 hwnd 或 None。"""
    EnumWindows = user32.EnumWindows
    GetWindowThreadProcessId = user32.GetWindowThreadProcessId
    GetWindowRect = user32.GetWindowRect
    IsWindowVisible = user32.IsWindowVisible

    EnumWindowsProcType = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    found: List[int] = []

    def _cb(hwnd, _lparam):
        if not IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc = _process_exe(pid.value)
        if proc and proc.lower().endswith(exe_name.lower()):
            rect = wintypes.RECT()
            if GetWindowRect(hwnd, ctypes.byref(rect)):
                w = rect.right - rect.left
                h = rect.bottom - rect.top
                if w > 200 and h > 200:  # 过滤系统小窗口
                    found.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProcType(_cb), 0)
    return found[0] if found else None


def _process_exe(pid: int) -> str:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    MAX_PATH = 260
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(MAX_PATH)
        size = wintypes.DWORD(MAX_PATH)
        try:
            kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
            return buf.value or ""
        except Exception:
            return ""
    finally:
        kernel32.CloseHandle(h)


def get_window_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    rect = wintypes.RECT()
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
    return None


def get_client_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """客户区左上角的屏幕坐标 + 客户区宽高（物理像素）。

    点 UI 按钮必须用客户区而不是整窗矩形：DPI 虚拟化下标题栏/边框会让
    整窗矩形换算出来的点击点整体偏移（实测 200% 缩放下偏一整条标题栏）。
    """
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    cw = rect.right - rect.left
    ch = rect.bottom - rect.top
    pt = wintypes.POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        return None
    return (pt.x, pt.y, cw, ch)


def is_foreground(hwnd: int) -> bool:
    """游戏窗口当前是否为前台（SendInput 只送进前台窗口，走位循环据此补抢焦点）。"""
    try:
        return bool(user32.GetForegroundWindow() == hwnd)
    except Exception:
        return False


def _force_foreground(hwnd: int) -> bool:
    """更强的前台激活：绕过 Windows 对 SetForegroundWindow 的前台限制。

    采用经典技巧：AttachThreadInput 到当前前台线程 -> SetForegroundWindow ->
    SendInput 模拟一次 ALT 键释放 -> Restore 善后。对全屏/独占游戏也有效。
    """
    foreground = user32.GetForegroundWindow()
    cur = kernel32.GetCurrentThreadId()
    if not foreground:
        fg_thread = 0
    else:
        try:
            fg_thread = user32.GetWindowThreadProcessId(foreground, None)
        except Exception:
            fg_thread = 0
    if cur != fg_thread:
        user32.AttachThreadInput(cur, fg_thread, True)
    user32.BringWindowToTop(hwnd)
    user32.ShowWindow(hwnd, 5)  # SW_SHOW
    user32.SetForegroundWindow(hwnd)
    user32.keybd_event(0x12, 0, 0, 0)      # ALT down
    user32.keybd_event(0x12, 0, 0x2, 0)    # ALT up
    if cur != fg_thread:
        user32.AttachThreadInput(cur, fg_thread, False)
    return bool(user32.GetForegroundWindow() == hwnd)


def ensure_foreground(hwnd: int) -> bool:
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    if not _force_foreground(hwnd):
        user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    g = user32.GetForegroundWindow()
    return bool(g == hwnd)


# ------------------------------------------------------------------ 截屏（GDI，纯 ctypes）
def capture_window(hwnd: int) -> Optional[Image.Image]:
    """抓取窗口客户区。点击和截图都用客户区，避免把标题栏算进画面。"""
    client = get_client_rect(hwnd)
    if not client:
        return None
    x, y, w, h = client
    if w <= 0 or h <= 0:
        return None

    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    try:
        bmp = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
        gdi32.SelectObject(hdc_mem, bmp)
        gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, x, y, 0x00CC0020)  # SRCCOPY

        # 复制到缓冲
        class _BMPHEADER(ctypes.Structure):
            _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG),
                        ("bmHeight", wintypes.LONG), ("bmWidthBytes", wintypes.LONG),
                        ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                        ("bmBits", ctypes.c_void_p)]

        bmi = _BMPHEADER()
        gdi32.GetObjectW(bmp, ctypes.sizeof(bmi), ctypes.byref(bmi))
        pitch = (bmi.bmWidthBytes + 3) // 4 * 4
        buf = ctypes.create_string_buffer(pitch * bmi.bmHeight)
        gdi32.GetBitmapBits(bmp, pitch * bmi.bmHeight, buf)
        # bmi 字节序为 BGRA（32bpp）或 BGR（24bpp）
        bpp = bmi.bmBitsPixel // 8
        img = Image.frombuffer("RGB", (bmi.bmWidth, bmi.bmHeight), buf, "raw",
                               "BGRX" if bpp == 4 else "BGR")
        # 注意：GDI BitBlt 位图第一行就是屏幕顶部，frombuffer 也是自上而下，
        # 这里不要再 transpose 翻转，否则截图会上下颠倒。
        return img
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(0, hdc_screen)