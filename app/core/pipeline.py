"""The batch queue.

Nothing here asks the user to open a folder. Films arrive as paths from a drag
or a dialog, the translation round trip happens in memory, and the finished
.srt is written beside the source video — the one place the editor is already
looking.

State is still kept on disk, so closing the window mid-batch loses nothing.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import asr, env, subtitles
from .termbase import Termbase

QUEUED = "queued"
AUDIO = "audio"
RECOGNISING = "recognising"
AWAITING = "awaiting"
ASSEMBLING = "assembling"
DONE = "done"
FAILED = "failed"

STATE_LABELS = {
    QUEUED: "В очереди",
    AUDIO: "Извлечение звука",
    RECOGNISING: "Распознавание",
    AWAITING: "Готов к переводу",
    ASSEMBLING: "Сборка титров",
    DONE: "Готово",
    FAILED: "Ошибка",
}

NUMBERED = re.compile(r"^\s*\**\s*\[?(\d{1,4})\]?\s*[.)\]:]?\s*\**\s*(.*)$")

PROMPT_TEMPLATE = """\
Переведи на румынский язык субтитры для телеэфира.{genre}

Требования:
1. Сохрани нумерацию ровно в том же виде: [1], [2], [3] и так далее.
2. Одна строка на входе — одна строка на выходе. Не объединяй и не разбивай.
3. Литературный румынский язык вещания, с полной диакритикой: ă â î ș ț.
4. Ничего не добавляй от себя, не комментируй, не пиши вступление.
5. Названия и имена — строго по списку ниже.

{terms}Текст:

{body}"""


@dataclass
class Job:
    source: Path
    name: str
    state: str = QUEUED
    progress: float = 0.0
    detail: str = ""
    sentences: list[asr.Sentence] = field(default_factory=list)
    parts: list[str] = field(default_factory=list)      # ready-to-copy prompts
    translated: dict[int, str] = field(default_factory=dict)
    srt_path: Path | None = None
    review: str = ""
    stale: bool = False
    duration: float = 0.0
    speed: float = 0.0
    started: float = 0.0
    log: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return STATE_LABELS.get(self.state, self.state)

    @property
    def key(self) -> str:
        return hashlib.sha1(str(self.source).encode("utf-8")).hexdigest()[:16]

    def part_done(self, index: int) -> bool:
        chunk = int(env.load_config()["translation"]["chunk_size"])
        wanted = {s.index for s in
                  self.sentences[index * chunk:(index + 1) * chunk]}
        return bool(wanted) and wanted <= set(self.translated)

    def missing(self) -> list[int]:
        return sorted({s.index for s in self.sentences} - set(self.translated))


class Pipeline:
    def __init__(self, notify: Callable[[], None]) -> None:
        self.jobs: list[Job] = []
        self.notify = notify
        self.recogniser = asr.Recogniser(self._engine_log)
        self.messages: list[str] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._restore()

    # -- lifecycle ---------------------------------------------------------- #

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _engine_log(self, message: str) -> None:
        self.messages.append(message)
        self.notify()

    def add(self, paths: list[Path]) -> tuple[int, int]:
        """Returns how many films were new and how many were sent round again.

        Dropping a film that is already in the list means "do it again" - most
        often because the recognition improved. Silently ignoring it left the
        user staring at an old result with no way to tell why."""
        added = requeued = 0
        with self._lock:
            existing = {str(job.source): job for job in self.jobs}
            for path in paths:
                if not path.is_file():
                    continue
                if path.suffix.lower() not in env.VIDEO_SUFFIXES:
                    continue
                job = existing.get(str(path))
                if job is None:
                    job = Job(source=path, name=path.stem)
                    self.jobs.append(job)
                    existing[str(path)] = job
                    added += 1
                elif job.state in (AWAITING, DONE, FAILED):
                    self._reset(job)
                    requeued += 1
        if added or requeued:
            self.notify()
        return added, requeued

    def _reset(self, job: Job) -> None:
        job.state = QUEUED
        job.stale = False       # a fresh run is never the old version's output
        job.progress = 0.0
        job.detail = ""
        job.sentences = []
        job.parts = []
        job.translated.clear()
        job.review = ""
        job.speed = 0.0

    def remove(self, job: Job) -> None:
        with self._lock:
            if job in self.jobs:
                self.jobs.remove(job)
        (env.SESSIONS / f"{job.key}.json").unlink(missing_ok=True)
        self.notify()

    def retry(self, job: Job) -> None:
        self._reset(job)
        self.notify()

    # -- main loop ---------------------------------------------------------- #

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._next_job()
                if job is not None:
                    self._process(job)
                else:
                    time.sleep(0.8)
            except Exception:
                self.messages.append(traceback.format_exc(limit=3))
                self.notify()
                time.sleep(3)

    def _next_job(self) -> Job | None:
        with self._lock:
            for job in self.jobs:
                if job.state == QUEUED:
                    return job
        return None

    # -- recognition -------------------------------------------------------- #

    def _process(self, job: Job) -> None:
        job.started = time.time()
        audio = env.TEMP / f"{job.key}.wav"
        try:
            if not job.source.exists():
                raise RuntimeError("Файл больше не доступен по прежнему пути")

            job.state = AUDIO
            job.detail = "Читаю файл"
            self.notify()
            asr.extract_audio(job.source, audio, job.log.append)
            job.duration = asr.media_duration(audio)

            job.state = RECOGNISING
            job.detail = "Загрузка модели — первый фильм всегда дольше"
            self.notify()

            termbase = Termbase.load()

            def progress(value: float) -> None:
                job.progress = value
                elapsed = time.time() - job.started
                if value > 0.02 and job.duration:
                    speed = (value * job.duration) / max(elapsed, 0.1)
                    job.speed = speed
                    left = (1 - value) * job.duration / max(speed, 0.01)
                    job.detail = (f"Осталось примерно {self._pretty(left)}"
                                  f" · {speed:.1f}× реального времени")
                self.notify()

            job.sentences = self.recogniser.transcribe(audio, termbase, progress)
            if not job.sentences:
                raise RuntimeError("В файле не распознано ни одной фразы")

            job.speed = self.recogniser.last_speed or job.speed
            job.parts = self._build_prompts(job, termbase)
            job.state = AWAITING
            job.progress = 1.0
            job.detail = (f"{len(job.sentences)} фраз"
                          + (f" · {len(job.parts)} части"
                             if len(job.parts) > 1 else "")
                          + (f" · распознано за {self._pretty(job.duration / job.speed)}"
                             f" ({job.speed:.1f}×)" if job.speed else ""))
            self._save(job)
        except Exception as exc:
            job.state = FAILED
            job.detail = str(exc)[:300]
            job.log.append(traceback.format_exc(limit=4))
        finally:
            audio.unlink(missing_ok=True)
            self.notify()

    @staticmethod
    def _pretty(seconds: float) -> str:
        if seconds < 90:
            return f"{max(int(seconds), 1)} сек"
        return f"{seconds / 60:.0f} мин"

    def _build_prompts(self, job: Job, termbase: Termbase) -> list[str]:
        chunk = int(env.load_config()["translation"]["chunk_size"])
        prompts: list[str] = []
        for start in range(0, len(job.sentences), chunk):
            part = job.sentences[start:start + chunk]
            body = "\n".join(f"[{s.index}] {s.text}" for s in part)
            reference = termbase.translation_reference(body)
            terms = ""
            if reference:
                listed = "\n".join(f"{k} = {v}" for k, v in reference.items())
                terms = f"Названия и имена:\n{listed}\n\n"
            genre = str(env.load_config()["translation"].get("genre", "") or "")
            prompts.append(PROMPT_TEMPLATE.format(
                genre=f" Материал: {genre}." if genre else "",
                terms=terms, body=body))
        return prompts

    # -- translation, entirely in memory ------------------------------------ #

    def apply_translation(self, job: Job, text: str) -> tuple[int, list[int]]:
        """Returns how many lines were accepted and what is still missing."""
        parsed = self._parse(text)
        wanted = {s.index for s in job.sentences}
        accepted = {k: v for k, v in parsed.items() if k in wanted}
        job.translated.update(accepted)

        missing = job.missing()
        if not missing:
            self._assemble(job)
        else:
            job.detail = (f"Принято {len(job.translated)} из {len(wanted)} · "
                          f"не хватает: {self._short(missing)}")
            self._save(job)
            self.notify()
        return len(accepted), missing

    @staticmethod
    def _short(numbers: list[int]) -> str:
        shown = ", ".join(str(n) for n in numbers[:12])
        return shown + (" и ещё…" if len(numbers) > 12 else "")

    def _assemble(self, job: Job) -> None:
        job.state = ASSEMBLING
        job.detail = "Собираю титры"
        self.notify()
        try:
            termbase = Termbase.load()
            spans = {s.index: (s.text, s.start, s.end) for s in job.sentences}
            order = sorted(spans)

            pairs = [(termbase.enforce(job.translated[i]),
                      spans[i][1], spans[i][2]) for i in order]
            russian = [spans[i][0] for i in order]

            cues = subtitles.build_cues(pairs)
            target = job.source.with_suffix(".srt")
            if target.exists():
                target = job.source.with_name(f"{job.source.stem}_RO.srt")
            subtitles.write_srt(cues, target)

            problems = subtitles.validate(cues)
            job.srt_path = target
            job.review = subtitles.review_text(pairs, russian)
            job.state = DONE
            job.progress = 1.0
            job.detail = (f"{len(cues)} титров · файл лежит рядом с видео"
                          + (f" · замечаний: {len(problems) - 1}"
                             if problems else ""))
            job.log.extend(problems)
            self._save(job)
        except Exception as exc:
            job.state = FAILED
            job.detail = f"Сборка не удалась: {str(exc)[:220]}"
            job.log.append(traceback.format_exc(limit=4))
        finally:
            self.notify()

    @staticmethod
    def _parse(text: str) -> dict[int, str]:
        """Survives markdown wrappers, '1.' numbering and wrapped long lines."""
        collected: dict[int, str] = {}
        current: int | None = None
        for raw in text.splitlines():
            line = raw.strip()
            # A wrapped sentence continues on the very next line. A blank line
            # means it ended, so a closing remark from the chat never gets glued
            # onto the last subtitle.
            if not line or line.startswith(("---", "===", "Текст:", "Требования")):
                current = None
                continue
            match = NUMBERED.match(line)
            if match:
                current = int(match.group(1))
                collected[current] = match.group(2).strip()
            elif current is not None:
                collected[current] = (collected[current] + " " + line).strip()
        return {k: v for k, v in collected.items() if v}

    # -- persistence -------------------------------------------------------- #

    def _save(self, job: Job) -> None:
        try:
            payload = {
                "source": str(job.source),
                "name": job.name,
                "state": job.state,
                "detail": job.detail,
                "saved": datetime.now().isoformat(timespec="seconds"),
                "app_version": env.VERSION,
                "srt": str(job.srt_path) if job.srt_path else "",
                "sentences": [{"i": s.index, "text": s.text,
                               "start": round(s.start, 3), "end": round(s.end, 3)}
                              for s in job.sentences],
                "translated": {str(k): v for k, v in job.translated.items()},
            }
            (env.SESSIONS / f"{job.key}.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _restore(self) -> None:
        if not env.SESSIONS.exists():
            return
        termbase = Termbase.load()
        for path in sorted(env.SESSIONS.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("state") not in (AWAITING, DONE):
                continue
            job = Job(source=Path(data["source"]), name=data["name"],
                      state=data["state"], progress=1.0,
                      detail=data.get("detail", ""))
            job.sentences = [asr.Sentence(int(s["i"]), s["text"],
                                          float(s["start"]), float(s["end"]))
                             for s in data.get("sentences", [])]
            job.translated = {int(k): v
                              for k, v in (data.get("translated") or {}).items()}
            if data.get("srt"):
                job.srt_path = Path(data["srt"])
            if job.state == AWAITING and job.sentences:
                job.parts = self._build_prompts(job, termbase)
                # Sentence splitting changes between releases. Text recognised
                # by an older build is still usable, but the user has to know
                # it will not reflect the fixes they just installed.
                if str(data.get("app_version", "")) != env.VERSION:
                    job.stale = True
                    job.detail = (f"{len(job.sentences)} фраз · распознано "
                                  f"версией {data.get('app_version') or '—'}. "
                                  f"Нажмите «Распознать заново», чтобы "
                                  f"применить исправления")
            self.jobs.append(job)
