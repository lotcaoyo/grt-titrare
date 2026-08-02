"""Cue segmentation, SRT writing and validation.

The Romanian text of a sentence is cut into cues strictly inside the time span
of the Russian sentence it translates. Timecodes therefore come from the audio,
never from the translation, and stay locked to the picture.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import env
from .termbase import normalise_romanian

# Places where a caption may be split without hurting readability, best first.
BREAK_PRIORITY = (
    re.compile(r"(?<=[.!?…])\s+"),
    re.compile(r"(?<=[:;])\s+"),
    re.compile(r"(?<=,)\s+"),
    re.compile(r"\s+(?=[-–—])"),
    re.compile(r"\s+"),
)


@dataclass
class Cue:
    index: int
    start: float
    end: float
    lines: list[str]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def cps(self) -> float:
        length = len(self.text.replace("\n", " "))
        return length / self.duration if self.duration > 0 else 999.0


# --------------------------------------------------------------------------- #
#  text shaping
# --------------------------------------------------------------------------- #

def _split_block(text: str, limit: int) -> list[str]:
    """Cut a sentence into blocks that each fit one caption."""
    text = text.strip()
    if len(text) <= limit:
        return [text]

    blocks: list[str] = []
    remainder = text
    while len(remainder) > limit:
        window = remainder[:limit + 1]
        cut = -1
        for pattern in BREAK_PRIORITY:
            candidates = [m.end() for m in pattern.finditer(window)]
            candidates = [c for c in candidates if c >= limit * 0.45]
            if candidates:
                cut = max(candidates)
                break
        if cut <= 0:
            cut = limit
        blocks.append(remainder[:cut].strip())
        remainder = remainder[cut:].strip()
    if remainder:
        blocks.append(remainder)
    return [b for b in blocks if b]


def _wrap(text: str, max_chars: int, max_lines: int) -> list[str]:
    """Balance a block over at most two lines, breaking at a sensible place."""
    if len(text) <= max_chars:
        return [text]

    best: tuple[int, int] | None = None      # (penalty, position)
    middle = len(text) / 2
    for match in re.finditer(r"\s+", text):
        position = match.start()
        head, tail = text[:position].strip(), text[position:].strip()
        if not head or not tail:
            continue
        if len(head) > max_chars or len(tail) > max_chars * max_lines:
            continue
        penalty = int(abs(position - middle))
        if re.search(r"[,.!?;:…]$", head):
            penalty -= 12                     # prefer breaking after punctuation
        if best is None or penalty < best[0]:
            best = (penalty, position)

    if best is None:
        return [text[:max_chars].strip(), text[max_chars:].strip()][:max_lines]

    head = text[:best[1]].strip()
    tail = text[best[1]:].strip()
    lines = [head] + (_wrap(tail, max_chars, max_lines - 1)
                      if max_lines > 1 else [tail])
    return lines[:max_lines]


# --------------------------------------------------------------------------- #
#  building
# --------------------------------------------------------------------------- #

def build_cues(pairs: list[tuple[str, float, float]]) -> list[Cue]:
    """pairs: Romanian text with the start and end of its Russian sentence."""
    config = env.load_config()["subtitles"]
    max_chars = int(config["max_chars_per_line"])
    max_lines = int(config["max_lines"])
    min_duration = float(config["min_duration"])
    max_duration = float(config["max_duration"])
    min_gap = float(config["min_gap"])
    max_cps = float(config["max_cps"])
    offset = float(config.get("offset", 0.0))

    limit = max_chars * max_lines
    cues: list[Cue] = []

    for text, start, end in pairs:
        text = normalise_romanian(text)
        if not text:
            continue
        span = max(end - start, 0.4)
        blocks = _split_block(text, limit)
        total = sum(len(b) for b in blocks) or 1

        cursor = start
        for position, block in enumerate(blocks):
            share = span * len(block) / total
            block_end = start + span if position == len(blocks) - 1 else cursor + share
            cues.append(Cue(0, cursor, max(block_end, cursor + 0.3),
                            _wrap(block, max_chars, max_lines)))
            cursor = block_end

    # Timing pass: readability first, then never let cues touch.
    for position, cue in enumerate(cues):
        following = cues[position + 1].start if position + 1 < len(cues) else None
        ceiling = (following - min_gap) if following is not None else cue.end + 3.0

        if cue.duration < min_duration:
            cue.end = min(cue.start + min_duration, max(ceiling, cue.start + 0.4))

        if cue.cps > max_cps:
            needed = len(cue.text.replace("\n", " ")) / max_cps
            cue.end = min(cue.start + needed, max(ceiling, cue.end))

        cue.end = min(cue.end, cue.start + max_duration)

        if following is not None and cue.end > following - min_gap:
            cue.end = max(following - min_gap, cue.start + 0.3)

    for number, cue in enumerate(cues, 1):
        cue.index = number
        cue.start = max(0.0, cue.start + offset)
        cue.end = max(cue.start + 0.3, cue.end + offset)
    return cues


# --------------------------------------------------------------------------- #
#  output
# --------------------------------------------------------------------------- #

def _timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    milliseconds = int(round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def write_srt(cues: list[Cue], path: Path) -> None:
    """UTF-8 without BOM and CRLF line endings.

    Premiere mangles Romanian diacritics when a BOM is present, which is the
    single most common reason an otherwise correct file looks broken on screen.
    """
    body = "".join(
        f"{cue.index}\r\n"
        f"{_timestamp(cue.start)} --> {_timestamp(cue.end)}\r\n"
        f"{cue.text}\r\n\r\n"
        for cue in cues
    )
    path.write_bytes(body.encode("utf-8"))


def validate(cues: list[Cue]) -> list[str]:
    config = env.load_config()["subtitles"]
    max_chars = int(config["max_chars_per_line"])
    max_cps = float(config["max_cps"])
    problems: list[str] = []

    for position, cue in enumerate(cues):
        if not cue.text.strip():
            problems.append(f"Титр {cue.index}: пустой")
        if cue.end <= cue.start:
            problems.append(f"Титр {cue.index}: нулевая длительность")
        for line in cue.lines:
            if len(line) > max_chars:
                problems.append(
                    f"Титр {cue.index}: строка {len(line)} символов "
                    f"при пределе {max_chars}")
        # Romanian runs longer than Russian, so mild overruns are structural,
        # not a defect. Only genuinely unreadable density is worth a line here.
        if cue.cps > max_cps + 4:
            problems.append(
                f"Титр {cue.index}: {cue.cps:.0f} символов в секунду — "
                f"плотно, стоит сократить фразу")
        if position + 1 < len(cues) and cue.end > cues[position + 1].start:
            problems.append(f"Титр {cue.index}: перекрывает следующий")

    if problems:
        problems.insert(0, f"Проверено титров: {len(cues)}. "
                           f"Замечаний: {len(problems)}.\n")
    return problems


def review_text(pairs: list[tuple[str, float, float]],
                russian: list[str]) -> str:
    """Side-by-side check, shown inside the window rather than written to disk."""
    lines = ["Слева русский оригинал, справа румынский титр.", ""]
    for position, (romanian, start, _end) in enumerate(pairs):
        source = russian[position] if position < len(russian) else ""
        lines.append(f"[{position + 1}]  {_timestamp(start)}")
        lines.append(f"  RU   {source}")
        lines.append(f"  RO   {romanian}")
        lines.append("")
    return "\n".join(lines)
