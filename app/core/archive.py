"""Register of finished subtitle files.

The .srt itself stays next to its video, because that is where the editor
opens it from. What was missing is a single place to find them all, so this
keeps an index rather than a second copy: nothing is duplicated, nothing goes
out of date, and a file deleted on disk simply drops out of the list.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import env

INDEX = env.DATA / "archive.json"


@dataclass
class Entry:
    name: str
    path: Path
    created: str
    cues: int
    source: str = ""

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @property
    def size_kb(self) -> float:
        try:
            return self.path.stat().st_size / 1024
        except OSError:
            return 0.0

    @property
    def when(self) -> str:
        try:
            moment = datetime.fromisoformat(self.created)
        except ValueError:
            return ""
        today = datetime.now().date()
        if moment.date() == today:
            return f"сегодня в {moment:%H:%M}"
        if (today - moment.date()).days == 1:
            return f"вчера в {moment:%H:%M}"
        return f"{moment:%d.%m.%Y в %H:%M}"

    def as_dict(self) -> dict:
        return {"name": self.name, "path": str(self.path),
                "created": self.created, "cues": self.cues,
                "source": self.source}


def _load() -> list[Entry]:
    if not INDEX.exists():
        return []
    try:
        raw = json.loads(INDEX.read_text(encoding="utf-8"))
    except Exception:
        return []
    entries = []
    for item in raw if isinstance(raw, list) else []:
        try:
            entries.append(Entry(name=item["name"], path=Path(item["path"]),
                                 created=item.get("created", ""),
                                 cues=int(item.get("cues", 0)),
                                 source=item.get("source", "")))
        except (KeyError, TypeError, ValueError):
            continue
    return entries


def _store(entries: list[Entry]) -> None:
    try:
        env.DATA.mkdir(parents=True, exist_ok=True)
        INDEX.write_text(
            json.dumps([e.as_dict() for e in entries], ensure_ascii=False),
            encoding="utf-8")
    except OSError:
        pass


def add(name: str, path: Path, cues: int, source: Path | None = None) -> None:
    entries = [e for e in _load() if e.path != path]
    entries.insert(0, Entry(name=name, path=path,
                            created=datetime.now().isoformat(timespec="seconds"),
                            cues=cues, source=str(source or "")))
    _store(entries[:500])


def items(include_missing: bool = False) -> list[Entry]:
    entries = _load()
    if include_missing:
        return entries
    return [e for e in entries if e.exists]


def ensure(name: str, path: Path, cues: int, source: str = "",
           created: str = "") -> bool:
    """Add only if this file is not indexed yet. Returns True when added."""
    entries = _load()
    if any(e.path == path for e in entries):
        return False
    entries.insert(0, Entry(
        name=name, path=path,
        created=created or datetime.now().isoformat(timespec="seconds"),
        cues=cues, source=source))
    entries.sort(key=lambda e: e.created, reverse=True)
    _store(entries[:500])
    return True


def count_cues(path: Path) -> int:
    """Cheap enough: an .srt is a few dozen kilobytes of text."""
    try:
        return path.read_text(encoding="utf-8", errors="replace").count(" --> ")
    except OSError:
        return 0


def backfill_from_sessions() -> int:
    """Pick up subtitle files produced before this register existed.

    A tool that quietly forgets yesterday's work is worse than one that never
    had a list, so the sessions on disk are treated as the source of truth and
    the index is rebuilt from them."""
    added = 0
    if not env.SESSIONS.exists():
        return 0
    for session in env.SESSIONS.glob("*.json"):
        try:
            data = json.loads(session.read_text(encoding="utf-8"))
        except Exception:
            continue
        srt = data.get("srt")
        if not srt:
            continue
        path = Path(srt)
        if not path.is_file():
            continue
        if ensure(name=data.get("name") or path.stem, path=path,
                  cues=count_cues(path), source=data.get("source", ""),
                  created=data.get("saved", "")):
            added += 1
    return added


def forget(path: Path) -> None:
    _store([e for e in _load() if e.path != path])


def read(entry: Entry) -> str:
    try:
        return entry.path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"Не удалось прочитать файл: {exc}"
