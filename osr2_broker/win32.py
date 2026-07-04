"""Win32 API wrappers for notifications and shutdown blocking."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

from .config import PROJECT_DIR

ICON_PATH = PROJECT_DIR / "broker_icon.ico"

# A distinct taskbar identity for this process. Without it, the warning
# dialog's taskbar button inherits the icon of the Python host process
# (pythonw.exe); with it, Windows uses the window's own broker icon.
APP_USER_MODEL_ID = "OSR2Broker"

_SetCurrentProcessExplicitAppUserModelID = (
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
)
_SetCurrentProcessExplicitAppUserModelID.argtypes = [wt.LPCWSTR]
_SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long  # HRESULT


def _set_app_user_model_id() -> None:
    """Claim a stable taskbar identity so windows show the broker icon."""
    _SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)


# --- Warning dialog (PyQt6, dark-themed via shared_ui) ---

def show_warning(title: str, message: str, button_text: str = "OK") -> None:
    """Show a dark-themed foreground warning dialog. Blocks until dismissed."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import (
        QApplication, QDialog, QHBoxLayout, QLabel,
        QPushButton, QStyle, QVBoxLayout,
    )

    from shared_ui.colors import (
        BG_BUTTON, BG_KEYCAP, BG_TERTIARY, BORDER_SUBTLE,
        TEXT_PRIMARY, TEXT_SECONDARY,
    )
    from shared_ui.fonts import SIZE_BODY, make_font
    from shared_ui.spacing import GAP_MEDIUM, MARGIN_STANDARD

    _set_app_user_model_id()
    app = QApplication.instance() or QApplication([])

    dlg = QDialog()
    dlg.setWindowTitle(title)
    dlg.setWindowIcon(QIcon(str(ICON_PATH)))
    dlg.setWindowFlags(
        Qt.WindowType.Dialog
        | Qt.WindowType.WindowTitleHint
        | Qt.WindowType.WindowCloseButtonHint
        | Qt.WindowType.WindowStaysOnTopHint
        | Qt.WindowType.MSWindowsFixedSizeDialogHint
    )

    dlg.setStyleSheet(f"""
        QDialog {{ background: {BG_TERTIARY.name()}; }}
        QLabel {{ color: {TEXT_SECONDARY.name()}; }}
        QPushButton {{
            color: {TEXT_PRIMARY.name()};
            background: {BG_BUTTON.name()};
            border: 1px solid {BORDER_SUBTLE.name()};
            padding: 4px 10px;
            border-radius: 3px;
        }}
        QPushButton:hover {{ background: {BG_KEYCAP.name()}; }}
        QPushButton:pressed {{ background: {BG_TERTIARY.name()}; }}
    """)

    body = QHBoxLayout()
    body.setSpacing(GAP_MEDIUM * 2)

    icon_lbl = QLabel()
    icon_lbl.setPixmap(
        dlg.style()
        .standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        .pixmap(32, 32)
    )
    icon_lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
    body.addWidget(icon_lbl)

    msg_lbl = QLabel(message)
    msg_lbl.setFont(make_font(size=SIZE_BODY))
    msg_lbl.setWordWrap(True)
    body.addWidget(msg_lbl, stretch=1)

    btn_row = QHBoxLayout()
    btn_row.addStretch()
    btn = QPushButton(button_text)
    btn.setFont(make_font(size=SIZE_BODY))
    btn.setDefault(True)
    btn.clicked.connect(dlg.accept)
    btn_row.addWidget(btn)

    outer = QVBoxLayout(dlg)
    m = MARGIN_STANDARD * 2
    outer.setContentsMargins(m, m, m, m)
    outer.setSpacing(GAP_MEDIUM * 2)
    outer.addLayout(body)
    outer.addLayout(btn_row)

    dlg.exec()


# --- Shutdown blocking via hidden window ---

WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
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


class ShutdownGuard:
    """Creates a hidden window that can block Windows shutdown.

    The message pump runs on the calling thread.  Call ``run()`` to start
    the pump (blocks until ``WM_DESTROY``).

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
