"""Film-specific terms.

Names are the one thing a translator renders differently on the second pass,
and the one thing an editor cannot skim past. Fixing them here turns
consistency from a matter of attention into a matter of the list being filled.

The proper nouns are pulled out of the transcript automatically, so the work is
filling in a right-hand column rather than hunting through the text.
"""

from __future__ import annotations

import tkinter as tk

from ..core import pipeline
from ..core.termbase import Termbase, candidates
from . import theme


class TermsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, engine: pipeline.Pipeline,
                 job: pipeline.Job) -> None:
        super().__init__(parent)
        self.engine = engine
        self.job = job

        self.title(f"Термины — {job.name}")
        self.configure(bg=theme.BG)
        self.geometry("620x620")
        self.minsize(520, 460)
        self.transient(parent)
        self.grab_set()

        head = tk.Frame(self, bg=theme.BG)
        head.pack(fill="x", padx=24, pady=(20, 0))
        theme.title(head, "Термины этого фильма", 15).pack(side="left")

        theme.body(self,
                   "Слева русское написание, справа румынское. Эти формы "
                   "уходят в перевод как обязательные, а после сборки "
                   "приложение проверит, что они действительно стоят "
                   "в каждой строке.",
                   theme.MUTED, 10, wrap=540).pack(fill="x", padx=24, pady=(8, 12))

        self.editor = tk.Text(
            self, bg=theme.BG, fg=theme.TEXT, font=theme.font(10),
            relief="flat", bd=0, wrap="none", padx=14, pady=12,
            highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT,
            highlightthickness=1)
        self.editor.pack(fill="both", expand=True, padx=24)

        footer = tk.Frame(self, bg=theme.BG)
        footer.pack(fill="x", padx=24, pady=(14, 18))
        self.status = theme.body(footer, "", theme.MUTED, 10, wrap=360)
        self.status.pack(side="left", fill="x", expand=True)
        theme.Button(footer, "Сохранить", self._save).pack(side="right")
        theme.Button(footer, "Отмена", self.destroy,
                     kind="secondary").pack(side="right", padx=(0, 8))

        self._fill()

    def _fill(self) -> None:
        lines = [f"{source} = {target}"
                 for source, target in sorted(self.job.terms.items())]

        known = dict(Termbase.load().pairs)
        known.update(self.job.terms)
        suggested = candidates(self.job.transcript, known)
        if suggested:
            if lines:
                lines.append("")
            lines.append("# Найдены в фильме — впишите румынский вариант:")
            lines += [f"{word} = " for word in suggested]

        if not lines:
            lines = ["# Имён собственных не найдено.",
                     "# Формат строки:  Комрат = Comrat"]

        self.editor.insert("1.0", "\n".join(lines))
        filled = len(self.job.terms)
        self.status.configure(
            text=f"Задано терминов: {filled}. Пустые строки не сохраняются.")

    def _save(self) -> None:
        terms: dict[str, str] = {}
        for raw in self.editor.get("1.0", "end").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            source, _, target = line.partition("=")
            source, target = source.strip(), target.strip()
            if source and target:
                terms[source] = target

        self.job.terms = terms
        self.engine.refresh_terms(self.job)
        self.destroy()
