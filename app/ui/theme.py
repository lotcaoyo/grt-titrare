"""Visual language of the application.

Flat surfaces, one accent colour, generous spacing and a single type scale.
Everything else on screen is text, which is what the user is actually reading.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont

BG = "#FFFFFF"
SURFACE = "#F5F5F7"
SURFACE_HI = "#EDEDF0"
BORDER = "#E2E2E6"
TEXT = "#1D1D1F"
MUTED = "#6E6E73"
FAINT = "#9A9AA0"
ACCENT = "#0071E3"
ACCENT_DARK = "#0060C0"
GREEN = "#2FA36B"
AMBER = "#C08207"
RED = "#D64541"

RADIUS_PAD = 14

_FAMILY = "Segoe UI"


def init(root: tk.Misc) -> None:
    global _FAMILY
    families = set(tkfont.families(root))
    for candidate in ("Segoe UI Variable Text", "Segoe UI", "Helvetica Neue", "Arial"):
        if candidate in families:
            _FAMILY = candidate
            break


def font(size: int = 11, weight: str = "normal") -> tuple:
    return (_FAMILY, size, weight)


def title(parent: tk.Misc, text: str, size: int = 20) -> tk.Label:
    return tk.Label(parent, text=text, bg=parent["bg"], fg=TEXT,
                    font=font(size, "bold"), anchor="w", justify="left")


def body(parent: tk.Misc, text: str, colour: str = MUTED,
         size: int = 10, wrap: int = 0) -> tk.Label:
    return tk.Label(parent, text=text, bg=parent["bg"], fg=colour,
                    font=font(size), anchor="w", justify="left",
                    wraplength=wrap or 0)


def card(parent: tk.Misc) -> tk.Frame:
    frame = tk.Frame(parent, bg=BG, highlightbackground=BORDER,
                     highlightcolor=BORDER, highlightthickness=1, bd=0)
    return frame


class Button(tk.Label):
    """Flat button. tk.Button on Windows forces a grey chrome we do not want."""

    def __init__(self, parent: tk.Misc, text: str, command,
                 kind: str = "primary", **kwargs) -> None:
        palette = {
            "primary": (ACCENT, "#FFFFFF", ACCENT_DARK),
            "secondary": (SURFACE, TEXT, SURFACE_HI),
            "quiet": (parent["bg"], ACCENT, SURFACE),
        }[kind]
        self._palette = palette
        self._command = command
        self._enabled = True
        super().__init__(parent, text=text, bg=palette[0], fg=palette[1],
                         font=font(10, "bold"), padx=18, pady=9,
                         cursor="hand2", **kwargs)
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", lambda _e: self._hover(True))
        self.bind("<Leave>", lambda _e: self._hover(False))

    def _click(self, _event) -> None:
        if self._enabled and self._command:
            self._command()

    def _hover(self, entering: bool) -> None:
        if not self._enabled:
            return
        self.configure(bg=self._palette[2] if entering else self._palette[0])

    def set_enabled(self, value: bool) -> None:
        self._enabled = value
        self.configure(
            bg=self._palette[0] if value else SURFACE,
            fg=self._palette[1] if value else FAINT,
            cursor="hand2" if value else "arrow",
        )

    def set_text(self, text: str) -> None:
        self.configure(text=text)


class Progress(tk.Canvas):
    """Slim bar with an indeterminate mode for steps of unknown length."""

    HEIGHT = 5

    def __init__(self, parent: tk.Misc, width: int = 320) -> None:
        super().__init__(parent, height=self.HEIGHT, width=width,
                         bg=parent["bg"], highlightthickness=0, bd=0)
        self._width = width
        self._value = 0.0
        self._marching = False
        self._offset = 0
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event) -> None:
        self._width = event.width
        self._redraw()

    def set(self, value: float) -> None:
        if value < 0:
            if not self._marching:
                self._marching = True
                self._march()
            return
        self._marching = False
        self._value = max(0.0, min(1.0, value))
        self._redraw()

    def _march(self) -> None:
        if not self._marching or not self.winfo_exists():
            return
        self._offset = (self._offset + 9) % max(self._width, 1)
        self.delete("all")
        self.create_rectangle(0, 0, self._width, self.HEIGHT,
                              fill=SURFACE_HI, outline="")
        span = max(self._width * 0.28, 60)
        start = self._offset - span
        self.create_rectangle(max(start, 0), 0,
                              min(start + span, self._width), self.HEIGHT,
                              fill=ACCENT, outline="")
        self.after(40, self._march)

    def _redraw(self) -> None:
        if not self.winfo_exists():
            return
        self.delete("all")
        self.create_rectangle(0, 0, self._width, self.HEIGHT,
                              fill=SURFACE_HI, outline="")
        if self._value > 0:
            self.create_rectangle(0, 0, self._width * self._value, self.HEIGHT,
                                  fill=ACCENT, outline="")


class Dot(tk.Canvas):
    """Status indicator. Colour carries the meaning, size stays constant."""

    SIZE = 10

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, width=self.SIZE, height=self.SIZE,
                         bg=parent["bg"], highlightthickness=0, bd=0)
        self._circle = self.create_oval(1, 1, self.SIZE - 1, self.SIZE - 1,
                                        fill=FAINT, outline="")

    def set(self, colour: str) -> None:
        self.itemconfigure(self._circle, fill=colour)


class Scrollable(tk.Frame):
    """Vertical scroll area whose inner frame always matches the canvas width."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, bg=BG)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        self.bar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=BG)

        self._window = self.canvas.create_window((0, 0), window=self.inner,
                                                 anchor="nw")
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.bar.pack(side="right", fill="y")

        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _on_inner(self, _event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    def _on_wheel(self, event) -> None:
        if self.winfo_ismapped():
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
