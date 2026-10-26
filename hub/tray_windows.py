#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PrintHub Pro - Windows system tray icon (pure stdlib, ctypes only).

Gives the hub a REAL identity on Windows:
  * a printer-badge icon in the tray area (bottom-right corner)
  * tooltip "PrintHub Pro vX.Y - running on http://127.0.0.1:PORT"
  * right-click menu:  Open status page / Print test page /
    Pause queue (check) / Share on network (check) /
    Copy connect code / Start at Windows logon (check) / Exit
  * double-click opens the status (health) page

Everything here is fail-safe: ANY error simply disables the tray and the
hub keeps printing. Nothing in this module may ever crash the hub.

The hub calls:
    import tray_windows
    tray_windows.start(icon=..., tooltip=..., callbacks={...})
Callbacks (all optional):
    on_open()            -> double-click / "Open status page"
    on_test()            -> "Print test page"
    is_paused()->bool    -> checkmark when menu is built
    on_pause_toggle()    -> user clicked Pause/Resume; returns new paused state
    is_autostart()->bool -> checkmark when menu is built
    on_autostart_toggle()-> user clicked Start at logon; returns new state
    is_shared()->bool    -> checkmark for "Share on network (LAN)" (v1.7.0)
    on_share_toggle()    -> user clicked Share on network; returns new state
    on_copy_share()      -> user clicked "Copy connect code (for other PCs)"
    on_exit()            -> "Exit"
"""

import ctypes
import os
import threading

APP = "PrintHub Pro"

# ---- win32 constants -------------------------------------------------
WM_NULL            = 0x0000
WM_DESTROY         = 0x0002
WM_CLOSE           = 0x0010
WM_QUIT            = 0x0012
WM_LBUTTONDBLCLK   = 0x0203
WM_RBUTTONUP       = 0x0205
WM_LBUTTONUP       = 0x0202
WM_USER            = 0x0400
WM_APP             = 0x8000
TRAY_MSG           = WM_APP + 20          # our callback message id
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP  = 0x01, 0x02, 0x04
IMAGE_ICON = 1
LR_LOADFROMFILE   = 0x00000010
LR_DEFAULTSIZE    = 0x00000040
IDI_APPLICATION   = 32512
MF_STRING, MF_SEPARATOR, MF_CHECKED = 0x00000000, 0x00000800, 0x00000008
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x0002, 0x0100, 0x0080
CS_VREDRAW, CS_HREDRAW = 0x0001, 0x0002
HWND_NOTOPMOST = -2
SW_HIDE = 0

# menu item ids (high word safety: keep < 0x8000)
M_OPEN, M_TEST, M_PAUSE, M_AUTO, M_EXIT = 1001, 1002, 1003, 1004, 1005
M_SHARE, M_COPY = 1006, 1007             # v1.7.0 network sharing

# ---- win32 types -----------------------------------------------------
user32   = ctypes.WinDLL("user32", use_last_error=True)
shell32  = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", ctypes.c_uint),
                ("lpfnWndProc", ctypes.WINFUNCTYPE(
                    ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint,
                    ctypes.c_size_t, ctypes.c_ssize_t)),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", ctypes.c_void_p),
                ("hIcon", ctypes.c_void_p),
                ("hCursor", ctypes.c_void_p),
                ("hbrBackground", ctypes.c_void_p),
                ("lpszMenuName", ctypes.c_wchar_p),
                ("lpszClassName", ctypes.c_wchar_p)]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
                ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
                ("time", ctypes.c_uint), ("pt", POINT)]


class NOTIFYICONDATAW(ctypes.Structure):
    # struct is 976 bytes on x64; we only fill the classic prefix + guid
    class _GUID(ctypes.Structure):
        _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort),
                    ("c", ctypes.c_ushort),
                    ("d", ctypes.c_ubyte * 8)]
    _fields_ = [("cbSize", ctypes.c_uint),
                ("hWnd", ctypes.c_void_p),
                ("uID", ctypes.c_uint),
                ("uFlags", ctypes.c_uint),
                ("uCallbackMessage", ctypes.c_uint),
                ("hIcon", ctypes.c_void_p),
                ("szTip", ctypes.c_wchar * 128),
                ("dwState", ctypes.c_uint),
                ("dwStateMask", ctypes.c_uint),
                ("szInfo", ctypes.c_wchar * 256),
                ("uVersion", ctypes.c_uint),
                ("szInfoTitle", ctypes.c_wchar * 64),
                ("dwInfoFlags", ctypes.c_uint),
                ("guidItem", _GUID),
                ("hBalloonIcon", ctypes.c_void_p)]


_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint,
    ctypes.c_size_t, ctypes.c_ssize_t)


class Tray(object):
    """One tray icon bound to one hidden message window."""

    def __init__(self, icon_path, tooltip, callbacks=None, logf=None):
        self.icon_path = icon_path or ""
        self.tooltip = (tooltip or APP)[:127]
        self.cb = callbacks or {}
        self.logf = logf or (lambda *a, **k: None)
        self.hwnd = None
        self.hicon = None
        self.uid = 7240                      # arbitrary, unique per process
        self._added = False
        self._alive = True
        self._tid = None

    # ---- helpers -----------------------------------------------------
    def _log(self, msg):
        try:
            self.logf("[TRAY] " + msg)
        except Exception:
            pass

    def _load_icon(self):
        if self.icon_path and os.path.isfile(self.icon_path):
            h = user32.LoadImageW(None, self.icon_path, IMAGE_ICON, 0, 0,
                                  LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if h:
                return h
        return user32.LoadIconW(None, IDI_APPLICATION)

    # ---- window ------------------------------------------------------
    def _register_and_create(self):
        self.wc = WNDCLASSW()
        self.wc.style = CS_VREDRAW | CS_HREDRAW
        self.wc.lpfnWndProc = _WNDPROC(self._wndproc)   # keep a reference!
        self.wc.hInstance = kernel32.GetModuleHandleW(None)
        self.wc.lpszClassName = "PrintHubProTrayWnd"
        self.wc.hIcon = self._load_icon()
        if not user32.RegisterClassW(ctypes.byref(self.wc)) \
                and kernel32.GetLastError() != 1410:     # already registered
            raise ctypes.WinError(kernel32.GetLastError())
        self.hicon = self.wc.hIcon
        self.hwnd = user32.CreateWindowExW(
            0, self.wc.lpszClassName, APP + " tray", 0x80000000,  # WS_POPUP
            0, 0, 0, 0, None, None, self.wc.hInstance, None)
        if not self.hwnd:
            raise ctypes.WinError(kernel32.GetLastError())

    def _add_icon(self):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = self.uid
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = TRAY_MSG
        nid.hIcon = self.hicon
        tip = self.tooltip
        nid.szTip = tip[:127]
        if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
            raise OSError("Shell_NotifyIconW(NIM_ADD) failed")
        self._added = True

    def _remove_icon(self):
        if self._added and self.hwnd:
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = self.hwnd
            nid.uID = self.uid
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            self._added = False

    # ---- message pump ------------------------------------------------
    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == TRAY_MSG:
                ev = lparam & 0xFFFF
                if ev in (WM_RBUTTONUP, WM_LBUTTONUP):
                    self._show_menu()
                elif ev == WM_LBUTTONDBLCLK:
                    self._cb("on_open")
                return 0
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                self._remove_icon()
                user32.PostQuitMessage(0)
                return 0
        except Exception as e:                     # never die on UI errors
            self._log("wndproc error: %r" % (e,))
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _cb(self, name):
        f = self.cb.get(name)
        if f:
            try:
                return f()
            except Exception as e:
                self._log("callback %s failed: %r" % (name, e))
        return None

    def _show_menu(self):
        paused = bool(self._cb("is_paused"))
        auto = bool(self._cb("is_autostart"))
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        user32.AppendMenuW(menu, MF_STRING, M_OPEN, "Open status page")
        user32.AppendMenuW(menu, MF_STRING, M_TEST, "Print test page")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING | (MF_CHECKED if paused else 0),
                           M_PAUSE, "Pause queue")
        shared = bool(self._cb("is_shared"))
        user32.AppendMenuW(menu,
                           MF_STRING | (MF_CHECKED if shared else 0),
                           M_SHARE, "Share on network (LAN)")
        user32.AppendMenuW(menu, MF_STRING, M_COPY,
                           "Copy connect code (for other PCs)")
        user32.AppendMenuW(menu, MF_STRING | (MF_CHECKED if auto else 0),
                           M_AUTO, "Start at Windows logon")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, M_EXIT, "Exit")
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        # foreground quirk: menu must be dismissed properly
        user32.SetForegroundWindow(self.hwnd)
        cmd = user32.TrackPopupMenu(
            menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
            pt.x, pt.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        if cmd == M_OPEN:
            self._cb("on_open")
        elif cmd == M_TEST:
            self._cb("on_test")
        elif cmd == M_PAUSE:
            new_paused = bool(self._cb("on_pause_toggle"))
            self._log("queue %s (tray)" % ("paused" if new_paused else "resumed"))
        elif cmd == M_AUTO:
            new_auto = bool(self._cb("on_autostart_toggle"))
            self._log("autostart %s (tray)" % ("ON" if new_auto else "OFF"))
        elif cmd == M_SHARE:
            new_shared = bool(self._cb("on_share_toggle"))
            self._log("network sharing %s (tray)"
                      % ("ON" if new_shared else "OFF"))
        elif cmd == M_COPY:
            self._cb("on_copy_share")
        elif cmd == M_EXIT:
            self._log("exit requested from tray")
            self.stop()
            self._cb("on_exit")

    # ---- lifecycle ---------------------------------------------------
    def run(self):
        try:
            self._register_and_create()
            self._add_icon()
        except Exception as e:
            self._log("tray unavailable: %r" % (e,))
            self._alive = False
            return
        self._log("tray icon running (tooltip: %s)" % self.tooltip)
        msg = MSG()
        while self._alive and user32.GetMessageW(ctypes.byref(msg),
                                                 None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        self._remove_icon()
        self._log("tray loop ended")

    def start_thread(self):
        self._tid = threading.Thread(target=self.run, name="printhub-tray",
                                     daemon=True)
        self._tid.start()

    def stop(self):
        self._alive = False
        try:
            if self.hwnd:
                user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        except Exception:
            pass


_SINGLETON = None


def start(icon, tooltip, callbacks=None, logf=None):
    """Start the tray icon thread. Returns True when the icon is (being)
    shown. Never raises."""
    global _SINGLETON
    try:
        _SINGLETON = Tray(icon, tooltip, callbacks, logf)
        _SINGLETON.start_thread()
        return True
    except Exception as e:                          # absolute last resort
        try:
            (logf or (lambda *a, **k: None))("[TRAY] start failed: %r" % (e,))
        except Exception:
            pass
        return False
