"""Vulture whitelist — false positives that are not dead code.

Each entry tells vulture the name is intentionally used, suppressing
the corresponding report.  Only add names here that are *provably*
called by a framework or accessed dynamically at runtime.
"""

# -- Win32 ctypes struct fields (WNDCLASSW) ----------------------------------
# Required by RegisterClassW; ctypes reads them from the struct layout.
lpfnWndProc  # noqa: F821
hInstance  # noqa: F821
lpszClassName  # noqa: F821

# -- pyserial property --------------------------------------------------------
# Set on the virtual serial port object; pyserial uses it internally.
write_timeout  # noqa: F821

# -- Qt QApplication ----------------------------------------------------------
# Must exist while any widget is alive; reference kept in local `app`.
app  # noqa: F821

# -- Dynamic attribute access (getattr / setattr) ----------------------------
# _write_activity() uses getattr(self, last_attr) / setattr(self, last_attr, now)
_last_rx_write  # noqa: F821
_last_tx_write  # noqa: F821
