"""The Components screen.

Every prerequisite is one row with one button. Two rules keep the window alive
while gigabytes are moving:

  * nothing checks anything on the interface thread — checks run in the
    background and the rows render a cached answer;
  * log and progress updates are coalesced, because pip emits hundreds of lines
    a second and redrawing on each one starves the event loop.
"""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
import webbrowser

from ..core import components as comp
from . import theme

DRIVER_URL = "https://www.nvidia.com/Download/index.aspx"
LOG_INTERVAL = 0.3          # seconds between redraws of a log view

COLOURS = {comp.READY: theme.GREEN, comp.MISSING: theme.AMBER,
           comp.BLOCKED: theme.RED, "unknown": theme.FAINT}


class ComponentRow(tk.Frame):
    def __init__(self, parent: tk.Misc, component: comp.Component,
                 view: "ComponentsView") -> None:
        super().__init__(parent, bg=theme.BG)
        self.component = component
        self.view = view
        self.busy = False
        self.state = "unknown"
        self._log_open = False
        self._log_due = 0.0
        self._log_pending = False

        card = theme.card(self)
        card.pack(fill="x")

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
            theme.body(line, f"  {component.size}",
                       theme.FAINT, 9).pack(side="left", pady=(2, 0))

        theme.body(labels, component.note, theme.FAINT, 9).pack(fill="x")
        self.detail = theme.body(labels, "Проверяю…", theme.MUTED, 10, wrap=540)
        self.detail.pack(fill="x", pady=(5, 0))

        self.action = theme.Button(head, self._idle_label(), self._clicked,
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

    def _idle_label(self) -> str:
        if not self.component.installable:
            return "Скачать драйвер"
        if self.component.key == "selftest":
            return "Проверить" if self.state != comp.READY else "Проверить снова"
        return "Переустановить" if self.state == comp.READY else "Установить"

    # -- rendering ---------------------------------------------------------- #

    def render(self, state: str, detail: str) -> None:
        """Called with a cached answer. Never computes anything itself."""
        self.state = state
        if self.busy:
            return
        self.dot.set(COLOURS.get(state, theme.FAINT))
        self.detail.configure(text=detail, fg=theme.MUTED)
        if not self.component.installable and state == comp.READY:
            self.action.pack_forget()
        else:
            if not self.action.winfo_ismapped():
                self.action.pack(side="right", pady=(2, 0))
            self.action.set_text(self._idle_label())
            self.action.set_enabled(True)

    # -- installing --------------------------------------------------------- #

    def _clicked(self) -> None:
        if self.busy:
            return
        if not self.component.installable:
            webbrowser.open(DRIVER_URL)
            return
        self.start()

    def start(self) -> None:
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
        self.dot.set(theme.ACCENT)
        self.detail.configure(text="Подготовка", fg=theme.MUTED)
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self) -> None:
        last = [0.0]

        def progress(value: float, caption: str) -> None:
            now = time.monotonic()
            if now - last[0] < 0.15 and value not in (1.0, -1):
                return                      # coalesce: the eye cannot see more
            last[0] = now
            self._safe(lambda: (self.progress.set(value),
                                self.detail.configure(text=caption)))

        def log(message: str) -> None:
            self.component.log.append(message)
            self._request_log_redraw()

        try:
            self.component.install(progress, log)
            self._safe(lambda: self._finish(None))
        except Exception as exc:
            self.component.log.append(f"ОШИБКА: {exc}")
            self._safe(lambda: self._finish(exc))

    def _safe(self, action) -> None:
        """Tk is not thread safe and after() from a worker is unreliable.
        Work is handed to the main thread through a queue it drains itself."""
        self.view.post(action)

    def _finish(self, error: Exception | None) -> None:
        self.busy = False
        self.progress.pack_forget()
        self.action.set_enabled(True)
        if error is None:
            self.action.set_text(self._idle_label())
            self.detail.configure(text="Установлено, проверяю…")
        else:
            self.dot.set(theme.RED)
            self.detail.configure(text=f"Не удалось: {error}", fg=theme.RED)
            self.action.set_text("Повторить")
            self._open_log()
        self._render_log()
        self.view.rescan()

    # -- log ---------------------------------------------------------------- #

    def _toggle_log(self) -> None:
        if self._log_open:
            self.log_view.pack_forget()
            self.log_button.set_text("Подробно")
            self._log_open = False
        else:
            self._open_log()

    def _open_log(self) -> None:
        if not self._log_open:
            self.spacer.pack_forget()
            if not self.log_button.winfo_ismapped():
                self.log_button.pack(anchor="w", padx=12, pady=(8, 0))
            self.log_view.pack(fill="x", padx=18, pady=(6, 0))
            self.spacer.pack(fill="x")
            self.log_button.set_text("Свернуть")
            self._log_open = True
        self._render_log()

    def _request_log_redraw(self) -> None:
        """pip prints faster than Tk can draw. Redraw on a timer instead."""
        if self._log_pending:
            return
        now = time.monotonic()
        if now < self._log_due:
            self._log_pending = True
            delay = int((self._log_due - now) * 1000) + 10
            self._safe(lambda: self.after(delay, self._flush_log))
            return
        self._log_due = now + LOG_INTERVAL
        self._safe(self._render_log)

    def _flush_log(self) -> None:
        self._log_pending = False
        self._log_due = time.monotonic() + LOG_INTERVAL
        self._render_log()

    def _render_log(self) -> None:
        if not self.component.log:
            return
        if not self.log_button.winfo_ismapped() and not self._log_open:
            self.spacer.pack_forget()
            self.log_button.pack(anchor="w", padx=12, pady=(8, 0))
            self.spacer.pack(fill="x")
        if not self._log_open:
            return
        self.log_view.configure(state="normal")
        self.log_view.delete("1.0", "end")
        self.log_view.insert("1.0", "\n".join(self.component.log[-200:]))
        self.log_view.see("end")
        self.log_view.configure(state="disabled")


class ComponentsView(tk.Frame):
    def __init__(self, parent: tk.Misc, on_ready_change,
                 on_first_scan=None) -> None:
        super().__init__(parent, bg=theme.BG)
        self.on_ready_change = on_ready_change
        self.on_first_scan = on_first_scan
        self.components = comp.all_components()
        self.states: dict[str, tuple[str, str]] = {}
        self._scanning = False
        self._first_done = False
        self._queue: list[ComponentRow] = []
        self._inbox: queue.Queue = queue.Queue()

        header = tk.Frame(self, bg=theme.BG)
        header.pack(fill="x", padx=28, pady=(24, 4))
        theme.title(header, "Компоненты").pack(side="left")
        self.install_all = theme.Button(header, "Установить всё",
                                        self._install_all)
        self.install_all.pack(side="right")

        self.note = theme.body(
            self, "Ставится в папку приложения. Права администратора не нужны, "
                  "система не затрагивается.", theme.MUTED, 10)
        self.note.pack(fill="x", padx=28, pady=(0, 14))

        area = theme.Scrollable(self)
        area.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        self.rows: list[ComponentRow] = []
        for component in self.components:
            row = ComponentRow(area.inner, component, self)
            row.pack(fill="x", padx=8, pady=6)
            self.rows.append(row)

        self.after(120, self._drain)
        self.rescan()

    # -- thread handover ----------------------------------------------------- #

    def post(self, action) -> None:
        """Safe to call from any thread."""
        self._inbox.put(action)

    def _drain(self) -> None:
        for _ in range(60):             # bounded, so a flood cannot block drawing
            try:
                action = self._inbox.get_nowait()
            except queue.Empty:
                break
            try:
                action()
            except tk.TclError:
                pass
        self.after(120, self._drain)

    # -- background checking ------------------------------------------------ #

    def rescan(self) -> None:
        if self._scanning:
            return
        self._scanning = True
        threading.Thread(target=self._scan, daemon=True).start()

    def _scan(self) -> None:
        results: dict[str, tuple[str, str]] = {}
        for component in self.components:
            try:
                results[component.key] = component.check()
            except Exception as exc:
                results[component.key] = (comp.BLOCKED,
                                          f"Проверка не удалась: {exc}"[:160])
        self.post(lambda: self._apply(results))

    def _apply(self, results: dict[str, tuple[str, str]]) -> None:
        self._scanning = False
        self.states = results
        for row in self.rows:
            state, detail = results.get(row.component.key, ("unknown", ""))
            row.render(state, detail)
        self.on_ready_change()
        if not self._first_done:
            self._first_done = True
            if self.on_first_scan:
                self.on_first_scan()

    def refresh(self) -> None:
        self.rescan()

    def ready(self) -> bool:
        required = ("ffmpeg", "engine", "model")
        return all(self.states.get(key, ("", ""))[0] == comp.READY
                   for key in required)

    # -- install everything -------------------------------------------------- #

    def _install_all(self) -> None:
        if self._queue:
            return
        order = {"ffmpeg": 0, "engine": 1, "cuda": 2, "model": 3,
                 "shortcut": 8, "selftest": 9}
        pending = [row for row in self.rows
                   if row.component.installable
                   and (self.states.get(row.component.key, ("", ""))[0] != comp.READY
                        or row.component.key == "selftest")]
        pending.sort(key=lambda r: order.get(r.component.key, 5))
        if not pending:
            return
        self.install_all.set_enabled(False)
        self.install_all.set_text("Идёт установка")
        self._queue = pending
        self._advance()

    def _advance(self) -> None:
        """Sequential on purpose: pip and large downloads fight for bandwidth."""
        if not self._queue:
            self.install_all.set_enabled(True)
            self.install_all.set_text("Установить всё")
            return
        head = self._queue[0]
        head.start()
        self._wait_for(head)

    def _wait_for(self, row: ComponentRow) -> None:
        if row.busy:
            self.after(300, lambda: self._wait_for(row))
            return
        if self._queue and self._queue[0] is row:
            self._queue.pop(0)
        self.after(200, self._advance)
