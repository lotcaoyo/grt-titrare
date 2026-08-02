"""Entry point.

Any crash before the window exists would otherwise be invisible under
pythonw.exe, so failures are written to disk and shown in a dialog.
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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
        from app.core import env
        env.ensure_dirs()
        env.enable_local_packages()
        from app.ui.window import App
        App().mainloop()
        return 0
    except BaseException as error:      # noqa: BLE001 - last line of defence
        _report(error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
