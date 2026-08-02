"""Window icon, set the way Windows expects.

Tk's own `iconbitmap` takes a single image out of the .ico and stretches it to
whatever size the system asks for. While the application is running, that
stretched picture overrides the icon compiled into the executable — which is
why the taskbar button looked soft even though the shortcut did not.

LoadImage picks the frame that matches the requested size exactly, and the two
sizes Windows actually asks for are the small icon (taskbar, title bar) and the
large one (Alt+Tab, task switcher). Both are set explicitly.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTCOLOR = 0x00000000
WM_SETICON = 0x0080
ICON_SMALL, ICON_BIG = 0, 1
SM_CXSMICON, SM_CYSMICON = 49, 50
SM_CXICON, SM_CYICON = 11, 12


def apply(window, ico: Path) -> bool:
    """Returns True when the icon was handed to Windows directly."""
    if sys.platform != "win32" or not ico.exists():
        return False

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                                      wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                      wintypes.UINT]
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                        wintypes.WPARAM, wintypes.LPARAM]
        user32.GetParent.restype = wintypes.HWND
        user32.GetParent.argtypes = [wintypes.HWND]

        window.update_idletasks()
        hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
        if not hwnd:
            return False

        handles = []
        for which, cx_metric, cy_metric in (
            (ICON_SMALL, SM_CXSMICON, SM_CYSMICON),
            (ICON_BIG, SM_CXICON, SM_CYICON),
        ):
            cx = user32.GetSystemMetrics(cx_metric)
            cy = user32.GetSystemMetrics(cy_metric)
            handle = user32.LoadImageW(None, str(ico), IMAGE_ICON, cx, cy,
                                       LR_LOADFROMFILE | LR_DEFAULTCOLOR)
            if not handle:
                return False
            user32.SendMessageW(hwnd, WM_SETICON, which, handle)
            handles.append(handle)

        # Keep the handles alive for as long as the window exists: freeing them
        # would leave Windows drawing from released memory.
        window._icon_handles = handles
        return True
    except Exception:      # noqa: BLE001 - cosmetic, never fatal
        return False
