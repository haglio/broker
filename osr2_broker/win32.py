"""Win32 API wrappers for notifications and shutdown blocking.

This module uses ctypes to call Win32 APIs directly — no external
dependencies needed.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import threading

# --- MessageBox ---

MB_OK = 0x00000000
MB_ICONWARNING = 0x00000030
MB_SETFOREGROUND = 0x00010000
MB_SYSTEMMODAL = 0x00001000

_MessageBoxW = ctypes.windll.user32.MessageBoxW
_MessageBoxW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.UINT]
_MessageBoxW.restype = ctypes.c_int


# --- CBT hook for custom MessageBox button text ---

WH_CBT = 5
HCBT_ACTIVATE = 5
IDOK = 1
WM_GETFONT = 0x0031
SWP_NOZORDER = 0x0004
BCM_GETIDEALSIZE = 0x1601

HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wt.WPARAM, wt.LPARAM)

_SetWindowsHookExW = ctypes.windll.user32.SetWindowsHookExW
_SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
_SetWindowsHookExW.restype = ctypes.c_void_p

_UnhookWindowsHookEx = ctypes.windll.user32.UnhookWindowsHookEx
_UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
_UnhookWindowsHookEx.restype = wt.BOOL

_CallNextHookEx = ctypes.windll.user32.CallNextHookEx
_CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wt.WPARAM, wt.LPARAM]
_CallNextHookEx.restype = ctypes.c_long

_SetDlgItemTextW = ctypes.windll.user32.SetDlgItemTextW
_SetDlgItemTextW.argtypes = [wt.HWND, ctypes.c_int, wt.LPCWSTR]
_SetDlgItemTextW.restype = wt.BOOL

_GetDlgItem = ctypes.windll.user32.GetDlgItem
_GetDlgItem.argtypes = [wt.HWND, ctypes.c_int]
_GetDlgItem.restype = wt.HWND

_GetCurrentThreadId = ctypes.windll.kernel32.GetCurrentThreadId
_GetCurrentThreadId.argtypes = []
_GetCurrentThreadId.restype = wt.DWORD

_GetWindowRect = ctypes.windll.user32.GetWindowRect
_GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
_GetWindowRect.restype = wt.BOOL

_SetWindowPos = ctypes.windll.user32.SetWindowPos
_SetWindowPos.argtypes = [
    wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wt.UINT,
]
_SetWindowPos.restype = wt.BOOL

_SendMessageW = ctypes.windll.user32.SendMessageW
_SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
_SendMessageW.restype = ctypes.c_long

_MapWindowPoints = ctypes.windll.user32.MapWindowPoints
_MapWindowPoints.argtypes = [wt.HWND, wt.HWND, ctypes.c_void_p, wt.UINT]
_MapWindowPoints.restype = ctypes.c_int


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


def show_warning(title: str, message: str, button_text: str = "OK") -> None:
    """Show a foreground warning dialog. Blocks until dismissed."""
    if button_text != "OK":
        hook_ref = [None]

        @HOOKPROC
        def _cbt_hook(code, wparam, lparam):
            if code == HCBT_ACTIVATE:
                hwnd = wt.HWND(wparam)
                btn = _GetDlgItem(hwnd, IDOK)
                if btn:
                    _SetDlgItemTextW(hwnd, IDOK, button_text)

                    # Resize only the button (not the dialog) to fit new text
                    ideal = _SIZE()
                    _SendMessageW(btn, BCM_GETIDEALSIZE, 0, ctypes.addressof(ideal))
                    if ideal.cx > 0:
                        btn_rect = wt.RECT()
                        _GetWindowRect(btn, ctypes.byref(btn_rect))
                        old_w = btn_rect.right - btn_rect.left
                        if ideal.cx > old_w:
                            pt = wt.POINT(btn_rect.left, btn_rect.top)
                            _MapWindowPoints(None, hwnd, ctypes.byref(pt), 1)
                            old_center = pt.x + old_w // 2
                            _SetWindowPos(
                                btn, None,
                                old_center - ideal.cx // 2, pt.y,
                                ideal.cx, btn_rect.bottom - btn_rect.top,
                                SWP_NOZORDER,
                            )
                _UnhookWindowsHookEx(hook_ref[0])
            return _CallNextHookEx(hook_ref[0], code, wparam, lparam)

        hook_ref[0] = _SetWindowsHookExW(
            WH_CBT, _cbt_hook, None, _GetCurrentThreadId(),
        )

    _MessageBoxW(
        None,
        message,
        title,
        MB_OK | MB_ICONWARNING | MB_SETFOREGROUND | MB_SYSTEMMODAL,
    )


# --- Shutdown blocking via hidden window ---

WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wt.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


_RegisterClassW = ctypes.windll.user32.RegisterClassW
_RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
_RegisterClassW.restype = wt.ATOM

_CreateWindowExW = ctypes.windll.user32.CreateWindowExW
_CreateWindowExW.argtypes = [
    wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID,
]
_CreateWindowExW.restype = wt.HWND

_DestroyWindow = ctypes.windll.user32.DestroyWindow
_DestroyWindow.argtypes = [wt.HWND]
_DestroyWindow.restype = wt.BOOL

_DefWindowProcW = ctypes.windll.user32.DefWindowProcW
_DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
_DefWindowProcW.restype = ctypes.c_long

_PostQuitMessage = ctypes.windll.user32.PostQuitMessage
_PostQuitMessage.argtypes = [ctypes.c_int]
_PostQuitMessage.restype = None

_GetMessageW = ctypes.windll.user32.GetMessageW
_GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
_GetMessageW.restype = wt.BOOL

_TranslateMessage = ctypes.windll.user32.TranslateMessage
_TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
_TranslateMessage.restype = wt.BOOL

_DispatchMessageW = ctypes.windll.user32.DispatchMessageW
_DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
_DispatchMessageW.restype = ctypes.c_long

_PostMessageW = ctypes.windll.user32.PostMessageW
_PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
_PostMessageW.restype = wt.BOOL

_ShutdownBlockReasonCreate = ctypes.windll.user32.ShutdownBlockReasonCreate
_ShutdownBlockReasonCreate.argtypes = [wt.HWND, wt.LPCWSTR]
_ShutdownBlockReasonCreate.restype = wt.BOOL

_ShutdownBlockReasonDestroy = ctypes.windll.user32.ShutdownBlockReasonDestroy
_ShutdownBlockReasonDestroy.argtypes = [wt.HWND]
_ShutdownBlockReasonDestroy.restype = wt.BOOL

_GetModuleHandleW = ctypes.windll.kernel32.GetModuleHandleW
_GetModuleHandleW.argtypes = [wt.LPCWSTR]
_GetModuleHandleW.restype = wt.HINSTANCE

_SetTimer = ctypes.windll.user32.SetTimer
_SetTimer.argtypes = [wt.HWND, ctypes.POINTER(wt.UINT), wt.UINT, wt.LPVOID]
_SetTimer.restype = ctypes.POINTER(wt.UINT)

WM_TIMER = 0x0113
WM_USER_POLL = 0x0400 + 1


class ShutdownGuard:
    """Creates a hidden window that can block Windows shutdown.

    The message pump runs on the calling thread. Call ``run()`` to start
    the pump; call ``request_stop()`` from any thread to exit.

    ``should_block_fn``: called on WM_QUERYENDSESSION. If it returns True,
    shutdown is blocked with ``ShutdownBlockReasonCreate``.

    ``poll_fn``: called every ``poll_interval_ms`` from within the message
    pump (WM_TIMER). Use this for periodic state checks.
    """

    CLASS_NAME = "OSR2BrokerShutdownGuard"

    def __init__(
        self,
        should_block_fn,
        poll_fn=None,
        poll_interval_ms: int = 10_000,
        block_reason: str = "OSR2 is still powered on!",
    ):
        self._should_block_fn = should_block_fn
        self._poll_fn = poll_fn
        self._poll_interval_ms = poll_interval_ms
        self._block_reason = block_reason
        self._hwnd: wt.HWND | None = None
        self._wndproc = WNDPROC(self._wnd_proc)

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_QUERYENDSESSION:
            if self._should_block_fn():
                _ShutdownBlockReasonCreate(hwnd, self._block_reason)
                return 0
            return 1

        if msg == WM_ENDSESSION:
            if wparam:
                _PostQuitMessage(0)
            return 0

        if msg == WM_TIMER:
            if self._poll_fn is not None:
                self._poll_fn()
            return 0

        if msg == WM_DESTROY:
            _PostQuitMessage(0)
            return 0

        return _DefWindowProcW(hwnd, msg, wparam, lparam)

    def run(self) -> None:
        hinstance = _GetModuleHandleW(None)

        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinstance
        wc.lpszClassName = self.CLASS_NAME
        _RegisterClassW(ctypes.byref(wc))

        self._hwnd = _CreateWindowExW(
            0, self.CLASS_NAME, "OSR2 Broker", 0,
            0, 0, 0, 0,
            None, None, hinstance, None,
        )

        _SetTimer(self._hwnd, None, self._poll_interval_ms, None)

        msg = wt.MSG()
        while _GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _TranslateMessage(ctypes.byref(msg))
            _DispatchMessageW(ctypes.byref(msg))

    def request_stop(self) -> None:
        if self._hwnd:
            _PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
