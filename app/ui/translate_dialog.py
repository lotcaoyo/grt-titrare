"""The translation step, done inside the window.

Two boxes and two buttons: copy what goes to the chat, paste what comes back.
No file is opened, saved or named by the user at any point.
"""

from __future__ import annotations

import tkinter as tk

from ..core import pipeline
from . import theme


class TranslateDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, engine: pipeline.Pipeline,
                 job: pipeline.Job) -> None:
        super().__init__(parent)
        self.engine = engine
        self.job = job
        self.part = self._first_unfinished()

        self.title(f"Перевод — {job.name}")
        self.configure(bg=theme.BG)
        self.geometry("760x680")
        self.minsize(620, 520)
        self.transient(parent)
        self.grab_set()

        self._build()
        self._load_part()

    def _first_unfinished(self) -> int:
        for index in range(len(self.job.parts)):
            if not self.job.part_done(index):
                return index
        return 0

    # -- layout ------------------------------------------------------------- #

    def _build(self) -> None:
        head = tk.Frame(self, bg=theme.BG)
        head.pack(fill="x", padx=24, pady=(20, 0))
        theme.title(head, self.job.name, 15).pack(side="left")
        self.part_label = theme.body(head, "", theme.MUTED, 10)
        self.part_label.pack(side="right", pady=(6, 0))

        # step one
        step1 = tk.Frame(self, bg=theme.BG)
        step1.pack(fill="x", padx=24, pady=(16, 0))
        theme.body(step1, "1. Скопируйте и отправьте в чат",
                   theme.TEXT, 11).pack(side="left")
        self.copy_button = theme.Button(step1, "Скопировать", self._copy)
        self.copy_button.pack(side="right")

        self.prompt_view = tk.Text(
            self, height=11, bg=theme.SURFACE, fg=theme.TEXT,
            font=theme.font(9), relief="flat", bd=0, wrap="word",
            padx=14, pady=12, insertwidth=0)
        self.prompt_view.pack(fill="both", expand=True, padx=24, pady=(9, 0))

        # step two
        step2 = tk.Frame(self, bg=theme.BG)
        step2.pack(fill="x", padx=24, pady=(18, 0))
        theme.body(step2, "2. Вставьте ответ сюда",
                   theme.TEXT, 11).pack(side="left")
        self.apply_button = theme.Button(step2, "Применить", self._apply)
        self.apply_button.pack(side="right")
        theme.Button(step2, "Вставить из буфера", self._paste,
                     kind="secondary").pack(side="right", padx=(0, 8))

        self.answer_view = tk.Text(
            self, height=11, bg=theme.BG, fg=theme.TEXT,
            font=theme.font(9), relief="flat", bd=0, wrap="word",
            padx=14, pady=12,
            highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT,
            highlightthickness=1)
        self.answer_view.pack(fill="both", expand=True, padx=24, pady=(9, 0))

        footer = tk.Frame(self, bg=theme.BG)
        footer.pack(fill="x", padx=24, pady=(12, 18))
        self.status = theme.body(footer, "", theme.MUTED, 10, wrap=520)
        self.status.pack(side="left", fill="x", expand=True)
        theme.Button(footer, "Закрыть", self.destroy,
                     kind="secondary").pack(side="right")

    # -- content ------------------------------------------------------------ #

    def _load_part(self) -> None:
        total = len(self.job.parts)
        self.part = max(0, min(self.part, total - 1))
        self.part_label.configure(
            text=f"Часть {self.part + 1} из {total}" if total > 1 else "")

        self.prompt_view.configure(state="normal")
        self.prompt_view.delete("1.0", "end")
        self.prompt_view.insert("1.0", self.job.parts[self.part])
        self.prompt_view.configure(state="disabled")

        self.answer_view.delete("1.0", "end")
        remaining = len(self.job.missing())
        self.status.configure(
            text=f"Осталось перевести фраз: {remaining}" if remaining else
                 "Все фразы переведены.", fg=theme.MUTED)
        self.copy_button.set_text("Скопировать")

    def _copy(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.job.parts[self.part])
        self.update()
        self.copy_button.set_text("Скопировано")
        self.after(1600, lambda: self.copy_button.set_text("Скопировать"))

    def _paste(self) -> None:
        try:
            text = self.clipboard_get()
        except tk.TclError:
            self.status.configure(text="В буфере обмена пусто", fg=theme.AMBER)
            return
        self.answer_view.delete("1.0", "end")
        self.answer_view.insert("1.0", text)

    def _apply(self) -> None:
        text = self.answer_view.get("1.0", "end").strip()
        if not text:
            self.status.configure(text="Сначала вставьте ответ из чата",
                                  fg=theme.AMBER)
            return

        accepted, missing = self.engine.apply_translation(self.job, text)
        if accepted == 0:
            self.status.configure(
                text="Не удалось разобрать ни одной строки. Нумерация вида "
                     "[1], [2] должна сохраниться.", fg=theme.RED)
            return

        if not missing:
            self.status.configure(
                text=f"Готово. Принято строк: {accepted}. "
                     f"Файл титров лежит рядом с видео.", fg=theme.GREEN)
            self.after(1400, self.destroy)
            return

        following = self._first_unfinished()
        if following != self.part:
            self.part = following
            self._load_part()
            self.status.configure(
                text=f"Часть принята. Осталось фраз: {len(missing)}. "
                     f"Скопируйте следующую часть.", fg=theme.GREEN)
        else:
            self.status.configure(
                text=f"Принято строк: {accepted}. Не хватает: "
                     f"{pipeline.Pipeline._short(missing)}. Допишите их "
                     f"в это же поле и нажмите «Применить».", fg=theme.AMBER)
