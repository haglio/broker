from __future__ import annotations

# Only a name a framework or the runtime provably reads.

# ctypes reads these from the WNDCLASSW struct layout.
lpfnWndProc
hInstance
lpszClassName

# pyserial reads it off the port object.
write_timeout

