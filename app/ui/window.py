"""Main window.

Background threads never touch widgets. They raise a flag, and the interface
polls it five times a second, which keeps Tk single threaded and removes an
entire class of race conditions.
"""

from __future__ import annotations

import re
import threading
import tkinter as tk

from ..core import env, gpu, pipeline, updater
from . import theme
from .archive_view import ArchiveView
from .components_view import ComponentsView
from .queue_view import QueueView

try:                                    # drag and drop is a nicety, not a need
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _Base = TkinterDnD.Tk
    _DND = True
except Exception:                       # noqa: BLE001
    _Base = tk.Tk
    DND_FILES = None
    _DND = False

TABS = (("work", "Титры"), ("archive", "Готово"), ("components", "Компоненты"))

# Windows hands over dropped paths as {C:/with spaces/a.mp4} C:/b.mp4
DROP_ITEM = re.compile(r"\{([^}]*)\}|(\S+)")


class App(_Base):
    def __init__(self) -> None:
        super().__init__()
        env.ensure_dirs()
        env.enable_local_packages()

        self.title("GRT Titrare")
        self.geometry("900x720")
        self.minsize(780, 580)
        self.configure(bg=theme.BG)
        theme.init(self)

        self._dirty = True
        self._update: updater.Release | None = None
        self.engine = pipeline.Pipeline(self._mark_dirty)

        self._build_tabs()
        self._build_banner()

        self.container = tk.Frame(self, bg=theme.BG)
        self.container.pack(fill="both", expand=True)

        self.views = {
            "work": QueueView(self.container, self.engine),
            "archive": ArchiveView(self.container),
            "components": ComponentsView(self.container, self._on_components,
                                         self._after_first_scan),
        }
        self._build_footer()
        self._enable_drop()

        self.current = ""
        self._touched = False
        self.show("components")

        self.engine.start()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(200, self._tick)
        self.after(1200, self._check_update)

    # -- chrome ------------------------------------------------------------- #

    def _build_tabs(self) -> None:
        bar = tk.Frame(self, bg=theme.BG)
        bar.pack(fill="x", padx=28, pady=(18, 0))

        strip = tk.Frame(bar, bg=theme.SURFACE)
        strip.pack(side="left")

        self.tab_buttons: dict[str, tk.Label] = {}
        for key, label in TABS:
            button = tk.Label(strip, text=label, bg=theme.SURFACE, fg=theme.MUTED,
                              font=theme.font(10, "bold"), padx=20, pady=8,
                              cursor="hand2")
            button.pack(side="left")
            button.bind("<Button-1>", lambda _e, k=key: self.show(k))
            self.tab_buttons[key] = button

        self.badge = theme.body(bar, "", theme.AMBER, 10)
        self.badge.pack(side="right", pady=(6, 0))

        tk.Frame(self, bg=theme.BORDER, height=1).pack(fill="x", pady=(14, 0))

    def _build_banner(self) -> None:
        self.banner = tk.Frame(self, bg="#EAF3FE")
        inner = tk.Frame(self.banner, bg="#EAF3FE")
        inner.pack(fill="x", padx=24, pady=10)
        self.banner_text = tk.Label(inner, text="", bg="#EAF3FE", fg=theme.TEXT,
                                    font=theme.font(10), anchor="w",
                                    justify="left")
        self.banner_text.pack(side="left", fill="x", expand=True)
        self.banner_action = theme.Button(inner, "Обновить", self._do_update)
        self.banner_action.pack(side="right")
        theme.Button(inner, "Позже", self._hide_banner,
                     kind="quiet").pack(side="right", padx=(0, 8))

    def _build_footer(self) -> None:
        tk.Frame(self, bg=theme.BORDER, height=1).pack(fill="x", side="bottom")
        footer = tk.Frame(self, bg=theme.BG)
        footer.pack(fill="x", side="bottom", padx=28, pady=9)
        self.status = theme.body(footer, "", theme.FAINT, 9)
        self.status.pack(side="left")
        theme.body(footer, f"GRT Titrare {env.VERSION}",
                   theme.FAINT, 9).pack(side="right")

    def show(self, key: str, by_user: bool = True) -> None:
        if by_user:
            self._touched = True
        if key == self.current:
            return
        for view in self.views.values():
            view.pack_forget()
        self.views[key].pack(fill="both", expand=True)
        self.current = key
        for tab_key, button in self.tab_buttons.items():
            active = tab_key == key
            button.configure(bg=theme.BG if active else theme.SURFACE,
                             fg=theme.TEXT if active else theme.MUTED)
        if key in ("components", "archive"):
            self.views[key].refresh()

    def _after_first_scan(self) -> None:
        """Everything already installed and the user has not clicked anything:
        open on the working screen instead of a wall of green ticks."""
        if not self._touched and self.views["components"].ready():
            self.show("work", by_user=False)

    # -- drag and drop ------------------------------------------------------ #

    def _enable_drop(self) -> None:
        zone = self.views["work"].drop
        if not _DND:
            zone.caption.configure(text="Добавьте фильмы")
            zone.hint.configure(text="можно сразу несколько")
            return
        for widget in (zone, zone.caption, zone.hint):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
            widget.dnd_bind("<<DropEnter>>", lambda _e: zone.highlight(True))
            widget.dnd_bind("<<DropLeave>>", lambda _e: zone.highlight(False))

    def _on_drop(self, event) -> None:
        from pathlib import Path
        self.views["work"].drop.highlight(False)
        paths = [Path(a or b) for a, b in DROP_ITEM.findall(event.data)]
        self.views["work"].accept([p for p in paths if p.exists()])

    # -- updates ------------------------------------------------------------ #

    def _check_update(self) -> None:
        if not env.load_config().get("update", {}).get("check_on_start", True):
            return

        def worker() -> None:
            release = updater.check()
            if release is not None:
                self.after(0, lambda: self._show_banner(release))

        threading.Thread(target=worker, daemon=True).start()

    def _show_banner(self, release: updater.Release) -> None:
        self._update = release
        notes = f" — {release.notes}" if release.notes else ""
        self.banner_text.configure(
            text=f"Доступна версия {release.version}{notes}")
        self.banner.pack(fill="x", before=self.container)

    def _hide_banner(self) -> None:
        self.banner.pack_forget()

    def _do_update(self) -> None:
        self.banner_action.set_enabled(False)
        self.banner_text.configure(text="Обновление…")

        def progress(_value: float, caption: str) -> None:
            self.after(0, lambda: self.banner_text.configure(text=caption))

        def worker() -> None:
            try:
                updater.install(progress, lambda m: None)
                self.after(0, self._restart)
            except Exception as exc:
                message = str(exc)[:180]
                self.after(0, lambda: (
                    self.banner_text.configure(
                        text=f"Обновить не удалось: {message}"),
                    self.banner_action.set_enabled(True)))

        threading.Thread(target=worker, daemon=True).start()

    def _restart(self) -> None:
        self.engine.stop()
        self.banner_text.configure(text="Перезапуск…")
        self.update()
        updater.restart()

    # -- state -------------------------------------------------------------- #

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _on_components(self) -> None:
        ready = self.views["components"].ready()
        self.badge.configure(text="" if ready else "Не все компоненты установлены")
        self._update_status()

    def _update_status(self) -> None:
        card = gpu.detect()   # cached after the first call
        mode = self.engine.recogniser.mode
        parts = [card.summary]
        if mode:
            parts.append(f"режим: {mode}")
        self.status.configure(text="  ·  ".join(parts))

    def _tick(self) -> None:
        if self._dirty:
            self._dirty = False
            try:
                self.views["work"].refresh()
                self._update_status()
                if self.current == "archive":
                    self.views["archive"].refresh()
            except tk.TclError:
                pass
        self.after(200, self._tick)

    def _close(self) -> None:
        self.engine.stop()
        self.destroy()
