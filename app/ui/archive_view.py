"""The finished-subtitles tab.

One list of every .srt the tool has produced, newest first, named after the
film. Each row does the three things actually needed: read it, open it, find
it on disk — plus a way to gather a whole batch into one folder when a set of
films has to travel together.
"""

from __future__ import annotations

import shutil
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

from ..core import archive, pipeline
from . import theme
from .queue_view import TextWindow, open_file, reveal


class ArchiveRow(tk.Frame):
    def __init__(self, parent: tk.Misc, entry: archive.Entry,
                 view: "ArchiveView") -> None:
        super().__init__(parent, bg=theme.BG)
        self.entry = entry
        self.view = view

        card = theme.card(self)
        card.pack(fill="x")

        top = tk.Frame(card, bg=theme.BG)
        top.pack(fill="x", padx=18, pady=(14, 0))

        labels = tk.Frame(top, bg=theme.BG)
        labels.pack(side="left", fill="x", expand=True)
        theme.body(labels, f"{entry.name}.srt", theme.TEXT, 12).pack(fill="x")
        if entry.exists:
            detail = f"{entry.cues} титров · {entry.size_kb:.0f} КБ"
            if entry.when:
                detail += f" · {entry.when}"
            theme.body(labels, detail, theme.MUTED, 10).pack(fill="x", pady=(3, 0))
        else:
            theme.body(labels, entry.diagnosis,
                       theme.RED, 10, wrap=520).pack(fill="x", pady=(3, 0))
            if view.can_rebuild(entry):
                theme.body(labels,
                           "Перевод сохранён — файл можно собрать заново, "
                           "ничего переводить не придётся.",
                           theme.MUTED, 9, wrap=520).pack(fill="x", pady=(2, 0))

        theme.body(top, str(entry.path.parent), theme.FAINT, 9).pack(
            side="right", pady=(4, 0))

        actions = tk.Frame(card, bg=theme.BG)
        actions.pack(fill="x", padx=14, pady=(8, 0))
        buttons = (
            (("Посмотреть", self._view, "secondary"),
             ("Открыть", self._open, "quiet"),
             ("Показать файл", self._reveal, "quiet"),
             ("Сохранить копию", self._save_copy, "quiet"))
            if entry.exists else
            ((("Собрать заново", self._rebuild, "primary"),)
             if view.can_rebuild(entry) else ())
            + (("Убрать из списка", self._forget, "quiet"),)
        )
        for label, command, kind in buttons:
            theme.Button(actions, label, command, kind=kind).pack(
                side="left", padx=(4, 0))

        tk.Frame(card, bg=theme.BG, height=14).pack(fill="x")

    def _rebuild(self) -> None:
        if self.view.rebuild(self.entry):
            self.view.flash("Файл собран заново")
        else:
            self.view.flash("Не удалось собрать — перевод неполный")
        self.view.refresh()

    def _forget(self) -> None:
        archive.forget(self.entry.path)
        self.view.refresh()

    def _view(self) -> None:
        TextWindow(self.winfo_toplevel(), f"{self.entry.name}.srt",
                   archive.read(self.entry))

    def _open(self) -> None:
        open_file(self.entry.path)

    def _reveal(self) -> None:
        reveal(self.entry.path)

    def _save_copy(self) -> None:
        target = filedialog.asksaveasfilename(
            title="Сохранить титры", defaultextension=".srt",
            initialfile=f"{self.entry.name}.srt",
            filetypes=[("Субтитры", "*.srt"), ("Все файлы", "*.*")])
        if not target:
            return
        try:
            shutil.copy2(self.entry.path, target)
            self.view.flash(f"Сохранено: {Path(target).name}")
        except OSError as exc:
            self.view.flash(f"Не удалось сохранить: {exc}")


class ArchiveView(tk.Frame):
    def __init__(self, parent: tk.Misc,
                 engine: pipeline.Pipeline | None = None) -> None:
        super().__init__(parent, bg=theme.BG)
        self.engine = engine
        self.entries: list[archive.Entry] = []

        header = tk.Frame(self, bg=theme.BG)
        header.pack(fill="x", padx=28, pady=(24, 6))
        theme.title(header, "Готовые титры").pack(side="left")
        theme.Button(header, "Собрать в папку", self._collect,
                     kind="secondary").pack(side="right")

        search = tk.Frame(self, bg=theme.BG)
        search.pack(fill="x", padx=28, pady=(0, 10))
        self.query = tk.StringVar()
        self.query.trace_add("write", lambda *_: self._render())
        box = tk.Entry(search, textvariable=self.query, font=theme.font(10),
                       relief="flat", bd=0, bg=theme.SURFACE, fg=theme.TEXT,
                       insertbackground=theme.TEXT)
        box.pack(fill="x", ipady=8, ipadx=12)
        self.placeholder = theme.body(self, "Поиск по названию фильма",
                                      theme.FAINT, 9)
        self.placeholder.pack(fill="x", padx=28, pady=(0, 8))

        self.notice = theme.body(self, "", theme.ACCENT, 10)

        self.area = theme.Scrollable(self)
        self.area.pack(fill="both", expand=True, padx=20, pady=(0, 8))
        self.empty = theme.body(
            self.area.inner,
            "Пока пусто. Как только фильм будет собран, титры появятся здесь "
            "под именем фильма.", theme.FAINT, 10, wrap=560)
        self.rows: list[ArchiveRow] = []

    # -- data ---------------------------------------------------------------- #

    def refresh(self) -> None:
        """Two sources, deliberately.

        The register survives restarts, the queue knows what was finished in
        this session. Merging them means a file can never be finished on one
        tab and invisible on the other, whatever went wrong with the index."""
        entries = {e.path: e for e in archive.items(include_missing=True)}

        if self.engine is not None:
            for job in self.engine.jobs:
                if job.state != pipeline.DONE or not job.srt_path:
                    continue
                if job.srt_path in entries:
                    continue
                cues = archive.count_cues(job.srt_path)
                archive.ensure(job.name, job.srt_path, cues, str(job.source))
                entries[job.srt_path] = archive.Entry(
                    name=job.name, path=job.srt_path,
                    created="", cues=cues, source=str(job.source))

        self.entries = sorted(entries.values(),
                              key=lambda e: (e.exists, e.created), reverse=True)
        self._render()

    def _render(self) -> None:
        needle = self.query.get().strip().lower()
        shown = [e for e in self.entries if needle in e.name.lower()]

        for row in self.rows:
            row.destroy()
        self.rows.clear()

        if not shown:
            self.empty.configure(
                text=("Ничего не найдено." if needle else
                      "Пока пусто. Как только фильм будет собран, титры "
                      "появятся здесь под именем фильма."))
            self.empty.pack(fill="x", padx=16, pady=10)
            self.placeholder.configure(
                text=f"Всего файлов: {len(self.entries)}" if self.entries
                else "Поиск по названию фильма")
            return

        self.empty.pack_forget()
        for entry in shown:
            row = ArchiveRow(self.area.inner, entry, self)
            row.pack(fill="x", padx=8, pady=6)
            self.rows.append(row)
        self.placeholder.configure(
            text=f"Показано {len(shown)} из {len(self.entries)}")

    def _job_for(self, entry: archive.Entry):
        if self.engine is None:
            return None
        for job in self.engine.jobs:
            if str(job.source) == entry.source or job.srt_path == entry.path:
                return job
        return None

    def can_rebuild(self, entry: archive.Entry) -> bool:
        job = self._job_for(entry)
        return bool(job and job.sentences and not job.missing())

    def rebuild(self, entry: archive.Entry) -> bool:
        job = self._job_for(entry)
        return bool(job and self.engine.rebuild(job))

    # -- actions -------------------------------------------------------------- #

    def flash(self, message: str) -> None:
        self.notice.configure(text=message)
        self.notice.pack(fill="x", padx=28, pady=(0, 6), before=self.area)
        self.after(4000, self.notice.pack_forget)

    def _collect(self) -> None:
        """Copy the whole visible batch into one folder, keeping film names."""
        needle = self.query.get().strip().lower()
        shown = [e for e in self.entries
                 if needle in e.name.lower() and e.exists]
        if not shown:
            self.flash("Нечего собирать")
            return

        folder = filedialog.askdirectory(title="Куда сложить титры")
        if not folder:
            return

        destination = Path(folder)
        copied = failed = 0
        for entry in shown:
            try:
                shutil.copy2(entry.path, destination / f"{entry.name}.srt")
                copied += 1
            except OSError:
                failed += 1
        self.flash(f"Скопировано файлов: {copied}"
                   + (f", не удалось: {failed}" if failed else ""))
