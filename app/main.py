"""Entry point.

Any crash before the window exists would otherwise be invisible under
pythonw.exe, so failures are written to disk and shown in a dialog.
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

# pythonw.exe runs without a console, so sys.stdout and sys.stderr are None.
# Any library that writes a progress bar - tqdm inside huggingface_hub and
# faster-whisper both do - then dies with "NoneType has no attribute write".
# This has to happen before those libraries are imported anywhere.
for _stream in ("stdout", "stderr"):
    if getattr(sys, _stream, None) is None:
        setattr(sys, _stream, open(os.devnull, "w", encoding="utf-8"))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

APP_ID = "GRT.Titrare"


def _claim_taskbar_identity() -> None:
    """Make Windows treat this as its own application, not as Python.

    A window started by pythonw.exe is grouped under the interpreter, and the
    taskbar shows the Python logo no matter what icon the window carries. An
    explicit AppUserModelID breaks that association, and must be set before the
    first window exists.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:      # noqa: BLE001 - cosmetic, never worth a crash
        pass


_claim_taskbar_identity()


def _report(error: BaseException) -> None:
    from app.core import env
    text = "".join(traceback.format_exception(type(error), error,
                                              error.__traceback__))
    try:
        env.LOGS.mkdir(parents=True, exist_ok=True)
        log = env.LOGS / f"crash-{datetime.now():%Y%m%d-%H%M%S}.txt"
        log.write_text(text, encoding="utf-8")
    except OSError:
        log = None
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "GRT Titrare",
            f"Приложение не смогло запуститься.\n\n{error}\n\n"
            + (f"Подробности: {log}" if log else ""))
        root.destroy()
    except Exception:
        print(text, file=sys.stderr)


def main() -> int:
    try:
        from app.core import env, housekeeping
        env.ensure_dirs()
        env.enable_local_packages()
        housekeeping.run()
        from app.ui.window import App
        App().mainloop()
        return 0
    except BaseException as error:      # noqa: BLE001 - last line of defence
        _report(error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
