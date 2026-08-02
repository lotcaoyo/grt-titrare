"""The Components screen.

Every prerequisite is one row with one button. Nothing here asks the user to
open a terminal, and no failure is allowed to disappear silently: the reason is
printed in the row that caused it.
"""

from __future__ import annotations

import threading
import tkinter as tk
import webbrowser

from ..core import components as comp
from . import theme

DRIVER_URL = "https://www.nvidia.com/Download/index.aspx"

COLOURS = {comp.READY: theme.GREEN, comp.MISSING: theme.AMBER,
           comp.BLOCKED: theme.RED}


class ComponentRow(tk.Frame):
    def __init__(self, parent: tk.Misc, component: comp.Component,
                 on_change) -> None:
        super().__init__(parent, bg=theme.BG)
        self.component = component
        self.on_change = on_change
        self.busy = False
        self._log_open = False

        card = theme.card(self)
        card.pack(fill="x")
        self.card = card

        head = tk.Frame(card, bg=theme.BG)
        head.pack(fill="x", padx=18, pady=(15, 0))

        self.dot = theme.Dot(head)
        self.dot.pack(side="left", pady=(6, 0))

        labels = tk.Frame(head, bg=theme.BG)
        labels.pack(side="left", fill="x", expand=True, padx=(11, 12))

        line = tk.Frame(labels, bg=theme.BG)
        line.pack(fill="x")
        theme.body(line, component.title, theme.TEXT, 12).pack(side="left")
        if component.size:
            self.size_label = theme.body(line, f"  {component.size}", theme.FAINT, 9)
            self.size_label.pack(side="left", pady=(2, 0))

        theme.body(labels, component.note, theme.FAINT, 9).pack(fill="x")
        self.detail = theme.body(labels, "", theme.MUTED, 10, wrap=560)
        self.detail.pack(fill="x", pady=(5, 0))

        first_label = "Проверить" if component.key == "selftest" else "Установить"
        self.action = theme.Button(head, first_label, self._install,
                                   kind="secondary")
        self.action.pack(side="right", pady=(2, 0))

        self.progress = theme.Progress(card)
        self.log_button = theme.Button(card, "Подробно", self._toggle_log,
                                       kind="quiet")
        self.log_view = tk.Text(card, height=7, bg=theme.SURFACE, fg=theme.MUTED,
                                font=("Consolas", 8), relief="flat", bd=0,
                                wrap="word", padx=12, pady=8)

        self.spacer = tk.Frame(card, bg=theme.BG, height=15)
        self.spacer.pack(fill="x")

        self.refresh()

    # -- state -------------------------------------------------------------- #

    def refresh(self) -> None:
        if self.busy:
            return
        state, detail = self.component.check()
        self.dot.set(COLOURS.get(state, theme.FAINT))
        self.detail.configure(text=detail)

        if not self.component.installable:
            if state == comp.READY:
                self.action.pack_forget()
            else:
                self.action.pack(side="right", pady=(2, 0))
                self.action.set_text("Скачать драйвер")
                self.action.set_enabled(True)
            return

        if state == comp.READY:
            self.action.set_text("Проверить снова" if self.component.key == "selftest" else "Переустановить")
            self.action.set_enabled(True)
        else:
            self.action.set_text(
                "Проверить" if self.component.key == "selftest" else "Установить")
            self.action.set_enabled(True)

    @property
    def state(self) -> str:
        return self.component.check()[0]

    # -- actions ------------------------------------------------------------ #

    def _install(self) -> None:
        if self.busy:
            return
        if not self.component.installable:
            webbrowser.open(DRIVER_URL)
            return
        self.start()

    def start(self) -> None:
        """Public: also used by the Install everything button."""
        if self.busy or not self.component.installable:
            return
        self.busy = True
        self.component.log.clear()
        self.action.set_enabled(False)
        self.action.set_text("Установка…")
        self.spacer.pack_forget()
        self.progress.pack(fill="x", padx=18, pady=(12, 0))
        self.spacer.pack(fill="x")
        self.progress.set(-1)
        self.detail.configure(text="Подготовка", fg=theme.MUTED)

        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self) -> None:
        def progress(value: float, caption: str) -> None:
            self._safe(lambda: (self.progress.set(value),
                                self.detail.configure(text=caption)))

        def log(message: str) -> None:
            self.component.log.append(message)
            self._safe(self._render_log)

        try:
            self.component.install(progress, log)
            self._safe(lambda: self._finish(None))
        except Exception as exc:
            self.component.log.append(f"ОШИБКА: {exc}")
            self._safe(lambda: self._finish(exc))

    def _safe(self, action) -> None:
        try:
            if self.winfo_exists():
                self.after(0, action)
        except tk.TclError:
            pass

    def _finish(self, error: Exception | None) -> None:
        self.busy = False
        self.progress.pack_forget()
        self.action.set_enabled(True)
        if error is None:
            self.refresh()
        else:
            self.dot.set(theme.RED)
            self.detail.configure(text=f"Не удалось: {error}", fg=theme.RED)
            self.action.set_text("Повторить")
            self._show_log()
        self.on_change()

    # -- log ---------------------------------------------------------------- #

    def _toggle_log(self) -> None:
        if self._log_open:
            self.log_view.pack_forget()
            self.log_button.set_text("Подробно")
            self._log_open = False
        else:
            self._show_log()

    def _show_log(self) -> None:
        if not self._log_open:
            self.spacer.pack_forget()
            self.log_button.pack(anchor="w", padx=12, pady=(8, 0))
            self.log_view.pack(fill="x", padx=18, pady=(6, 0))
            self.spacer.pack(fill="x")
            self.log_button.set_text("Свернуть")
            self._log_open = True
        self._render_log()

    def _render_log(self) -> None:
        if not self._log_open:
            if self.component.log and not self.log_button.winfo_ismapped():
                self.spacer.pack_forget()
                self.log_button.pack(anchor="w", padx=12, pady=(8, 0))
                self.spacer.pack(fill="x")
            return
        self.log_view.configure(state="normal")
        self.log_view.delete("1.0", "end")
        self.log_view.insert("1.0", "\n".join(self.component.log[-300:]))
        self.log_view.see("end")
        self.log_view.configure(state="disabled")


class ComponentsView(tk.Frame):
    def __init__(self, parent: tk.Misc, on_ready_change) -> None:
        super().__init__(parent, bg=theme.BG)
        self.on_ready_change = on_ready_change
        self.components = comp.all_components()

        header = tk.Frame(self, bg=theme.BG)
        header.pack(fill="x", padx=28, pady=(24, 4))
        theme.title(header, "Компоненты").pack(side="left")

        self.install_all = theme.Button(header, "Установить всё",
                                        self._install_all)
        self.install_all.pack(side="right")

        theme.body(self, "Ставится в папку приложения. Права администратора "
                         "не нужны, система не затрагивается.",
                   theme.MUTED, 10).pack(fill="x", padx=28, pady=(0, 14))

        area = theme.Scrollable(self)
        area.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        self.rows: list[ComponentRow] = []
        for component in self.components:
            row = ComponentRow(area.inner, component, self._changed)
            row.pack(fill="x", padx=8, pady=6)
            self.rows.append(row)

    def _install_all(self) -> None:
        order = {"ffmpeg": 0, "engine": 1, "cuda": 2, "model": 3, "selftest": 9}
        pending = [row for row in self.rows
                   if row.component.installable
                   and (row.state != comp.READY or row.component.key == "selftest")]
        pending.sort(key=lambda r: order.get(r.component.key, 5))
        self._chain(pending)

    def _chain(self, rows: list[ComponentRow]) -> None:
        """Sequential, not parallel: pip and large downloads fight for bandwidth."""
        if not rows:
            self._changed()
            return
        head, tail = rows[0], rows[1:]
        head.start()

        def wait() -> None:
            if head.busy:
                self.after(400, wait)
            else:
                self._chain(tail)

        self.after(400, wait)

    def _changed(self) -> None:
        for row in self.rows:
            row.refresh()
        self.on_ready_change()

    def refresh(self) -> None:
        self._changed()

    def ready(self) -> bool:
        return comp.ready_to_work(self.components)
