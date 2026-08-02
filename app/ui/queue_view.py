"""The working screen.

Films are dropped onto the window or picked from a dialog. Everything after
that — progress, translation, the finished file — is reachable from the card
that represents the film. There is no folder to visit.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

from ..core import env, pipeline
from . import theme
from .terms_dialog import TermsDialog
from .translate_dialog import TranslateDialog

STATE_COLOURS = {
    pipeline.QUEUED: theme.FAINT,
    pipeline.AUDIO: theme.ACCENT,
    pipeline.RECOGNISING: theme.ACCENT,
    pipeline.AWAITING: theme.AMBER,
    pipeline.ASSEMBLING: theme.ACCENT,
    pipeline.DONE: theme.GREEN,
    pipeline.FAILED: theme.RED,
}


def reveal(path: Path) -> None:
    """Show the file in Explorer, selected. Used only when the user asks."""
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    except OSError:
        pass


def open_file(path: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError:
        pass


class TextWindow(tk.Toplevel):
    """Read-only viewer, so checking the transcript never means opening a file."""

    def __init__(self, parent: tk.Misc, title: str, content: str) -> None:
        super().__init__(parent)
        self.title(title)
        self.configure(bg=theme.BG)
        self.geometry("720x600")
        self.transient(parent)

        view = tk.Text(self, bg=theme.BG, fg=theme.TEXT, font=theme.font(9),
                       relief="flat", bd=0, wrap="word", padx=18, pady=14)
        bar = tk.Scrollbar(self, command=view.yview)
        view.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        view.pack(fill="both", expand=True)
        view.insert("1.0", content)
        view.configure(state="disabled")


class JobCard(tk.Frame):
    def __init__(self, parent: tk.Misc, job: pipeline.Job,
                 view: "QueueView") -> None:
        super().__init__(parent, bg=theme.BG)
        self.job = job
        self.view = view

        card = theme.card(self)
        card.pack(fill="x")

        top = tk.Frame(card, bg=theme.BG)
        top.pack(fill="x", padx=18, pady=(14, 0))

        self.dot = theme.Dot(top)
        self.dot.pack(side="left", pady=(5, 0))

        labels = tk.Frame(top, bg=theme.BG)
        labels.pack(side="left", fill="x", expand=True, padx=(11, 10))
        theme.body(labels, job.name, theme.TEXT, 12).pack(fill="x")
        self.detail = theme.body(labels, "", theme.MUTED, 10, wrap=470)
        self.detail.pack(fill="x", pady=(3, 0))

        self.state = theme.body(top, "", theme.MUTED, 10)
        self.state.pack(side="right", pady=(4, 0))

        self.progress = theme.Progress(card)
        self.progress.pack(fill="x", padx=18, pady=(11, 0))

        self.actions = tk.Frame(card, bg=theme.BG)
        self.actions.pack(fill="x", padx=14, pady=(6, 0))
        self._buttons: list[tk.Widget] = []

        tk.Frame(card, bg=theme.BG, height=12).pack(fill="x")
        self.update_view()

    def _set_actions(self, spec: list[tuple[str, object, str]]) -> None:
        signature = [item[0] for item in spec]
        if getattr(self, "_signature", None) == signature:
            return
        self._signature = signature
        for widget in self._buttons:
            widget.destroy()
        self._buttons.clear()
        for label, command, kind in spec:
            button = theme.Button(self.actions, label, command, kind=kind)
            button.pack(side="left", padx=(4, 0))
            self._buttons.append(button)

    def update_view(self) -> None:
        job = self.job
        colour = STATE_COLOURS.get(job.state, theme.FAINT)
        self.dot.set(colour)
        self.state.configure(text=job.label, fg=colour)
        self.detail.configure(text=job.detail or " ")

        if job.state in (pipeline.AUDIO, pipeline.RECOGNISING):
            self.progress.set(job.progress if job.progress > 0 else -1)
        elif job.state == pipeline.ASSEMBLING:
            self.progress.set(-1)
        elif job.state in (pipeline.DONE, pipeline.AWAITING):
            self.progress.set(1.0)
        else:
            self.progress.set(0.0)

        if job.state == pipeline.AWAITING and job.stale:
            self._set_actions([
                ("Распознать заново", self._retry, "primary"),
                ("Перевести как есть", self._translate, "quiet"),
                ("Расшифровка", self._show_transcript, "quiet"),
                ("Убрать", self._remove, "quiet"),
            ])
        elif job.state == pipeline.AWAITING:
            terms = (f"Термины ({len(job.terms)})" if job.terms else "Термины")
            self._set_actions([
                ("Перевести", self._translate, "primary"),
                (terms, self._edit_terms, "secondary"),
                ("Расшифровка", self._show_transcript, "quiet"),
                ("Убрать", self._remove, "quiet"),
            ])
        elif job.state == pipeline.DONE:
            self._set_actions([
                ("Открыть титры", self._open_srt, "secondary"),
                ("Сверка RU / RO", self._show_review, "quiet"),
                ("Проверка", self._show_log, "quiet"),
                ("Убрать", self._remove, "quiet"),
            ])
        elif job.state == pipeline.FAILED:
            self._set_actions([
                ("Повторить", self._retry, "secondary"),
                ("Подробно", self._show_log, "quiet"),
                ("Убрать", self._remove, "quiet"),
            ])
        else:
            self._set_actions([("Убрать", self._remove, "quiet")])

    # -- actions ------------------------------------------------------------ #

    def _translate(self) -> None:
        TranslateDialog(self.winfo_toplevel(), self.view.engine, self.job)

    def _edit_terms(self) -> None:
        TermsDialog(self.winfo_toplevel(), self.view.engine, self.job)

    def _show_transcript(self) -> None:
        text = "\n".join(f"[{s.index}] {s.text}" for s in self.job.sentences)
        TextWindow(self.winfo_toplevel(), f"Расшифровка — {self.job.name}", text)

    def _show_review(self) -> None:
        TextWindow(self.winfo_toplevel(), f"Сверка — {self.job.name}",
                   self.job.review or "Сверка недоступна")

    def _show_log(self) -> None:
        TextWindow(self.winfo_toplevel(), f"Журнал — {self.job.name}",
                   "\n".join(self.job.log) or self.job.detail)

    def _open_srt(self) -> None:
        if self.job.srt_path and self.job.srt_path.exists():
            open_file(self.job.srt_path)

    def _reveal(self) -> None:
        if self.job.srt_path and self.job.srt_path.exists():
            reveal(self.job.srt_path)

    def _retry(self) -> None:
        self.view.engine.retry(self.job)

    def _remove(self) -> None:
        self.view.forget(self.job)


class DropZone(tk.Frame):
    """The only entry point for work. Accepts a drag or opens a dialog."""

    def __init__(self, parent: tk.Misc, on_files) -> None:
        super().__init__(parent, bg=theme.SURFACE, height=118)
        self.on_files = on_files
        self.pack_propagate(False)

        inner = tk.Frame(self, bg=theme.SURFACE)
        inner.place(relx=0.5, rely=0.5, anchor="center")
        self.caption = tk.Label(
            inner, text="Перетащите фильмы сюда",
            bg=theme.SURFACE, fg=theme.TEXT, font=theme.font(13, "bold"))
        self.caption.pack()
        self.hint = tk.Label(
            inner, text="можно сразу несколько · или",
            bg=theme.SURFACE, fg=theme.MUTED, font=theme.font(10))
        self.hint.pack(pady=(4, 6))
        theme.Button(inner, "Выбрать файлы", self._choose,
                     kind="secondary").pack()

    def _choose(self) -> None:
        chosen = filedialog.askopenfilenames(
            title="Выберите фильмы",
            filetypes=[("Видео и аудио",
                        " ".join(f"*{s}" for s in sorted(env.VIDEO_SUFFIXES))),
                       ("Все файлы", "*.*")])
        if chosen:
            self.on_files([Path(p) for p in chosen])

    def highlight(self, active: bool) -> None:
        colour = theme.SURFACE_HI if active else theme.SURFACE
        self.configure(bg=colour)
        for widget in (self.caption, self.hint):
            widget.configure(bg=colour)
            widget.master.configure(bg=colour)


class QueueView(tk.Frame):
    def __init__(self, parent: tk.Misc, engine: pipeline.Pipeline) -> None:
        super().__init__(parent, bg=theme.BG)
        self.engine = engine
        self.cards: dict[str, JobCard] = {}

        header = tk.Frame(self, bg=theme.BG)
        header.pack(fill="x", padx=28, pady=(24, 10))
        theme.title(header, "Титры").pack(side="left")
        self.summary = theme.body(header, "", theme.MUTED, 10)
        self.summary.pack(side="right", pady=(9, 0))

        self.drop = DropZone(self, self.accept)
        self.drop.pack(fill="x", padx=28, pady=(0, 6))

        self.notice = theme.body(self, "", theme.ACCENT, 10)

        self.area = theme.Scrollable(self)
        self.area.pack(fill="both", expand=True, padx=20, pady=(6, 8))

        self.empty = theme.body(
            self.area.inner,
            "Готовый файл титров появится рядом с самим видео. "
            "Из приложения выходить не нужно.",
            theme.FAINT, 10)
        self.empty.pack(fill="x", padx=16, pady=10)

    def accept(self, paths: list[Path]) -> None:
        added, requeued = self.engine.add(paths)
        if requeued:
            self.flash(f"Запускаю заново: {requeued}")
        elif not added:
            self.flash("Это не видеофайлы")

    def flash(self, message: str) -> None:
        """Notices belong where the eye already is, not in a corner that the
        next refresh overwrites."""
        self.notice.configure(text=message)
        self.notice.pack(fill="x", padx=28, pady=(0, 8), before=self.area)
        self.after(4000, self.notice.pack_forget)

    def forget(self, job: pipeline.Job) -> None:
        card = self.cards.pop(job.name, None)
        if card is not None:
            card.destroy()
        self.engine.remove(job)

    def refresh(self) -> None:
        for job in list(self.engine.jobs):
            card = self.cards.get(job.name)
            if card is None:
                card = JobCard(self.area.inner, job, self)
                card.pack(fill="x", padx=8, pady=6)
                self.cards[job.name] = card
            card.update_view()

        if self.engine.jobs:
            self.empty.pack_forget()
        else:
            self.empty.pack(fill="x", padx=16, pady=10)
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        jobs = self.engine.jobs
        if not jobs:
            self.summary.configure(text="")
            return
        counts = {
            "в работе": sum(1 for j in jobs if j.state in
                            (pipeline.AUDIO, pipeline.RECOGNISING,
                             pipeline.ASSEMBLING)),
            "в очереди": sum(1 for j in jobs if j.state == pipeline.QUEUED),
            "ждут перевода": sum(1 for j in jobs if j.state == pipeline.AWAITING),
            "готово": sum(1 for j in jobs if j.state == pipeline.DONE),
            "с ошибкой": sum(1 for j in jobs if j.state == pipeline.FAILED),
        }
        parts = [f"всего {len(jobs)}"]
        parts += [f"{label} {value}" for label, value in counts.items() if value]
        self.summary.configure(text=" · ".join(parts))
