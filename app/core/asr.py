"""Speech recognition and sentence assembly.

Timing is decided here and nowhere else. Every subtitle later inherits the time
span of the Russian sentence it came from, so a longer Romanian translation can
never push the timecodes out of sync with the picture.
"""

from __future__ import annotations

import inspect
import re
import subprocess
from dataclasses import dataclass
import time
from pathlib import Path
from typing import Callable, Iterator

from . import env, gpu
from .termbase import Termbase

# Whisper invents these during silence and music. They are not transcription.
NOISE_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in (
        r"^\s*[\[\(].{0,40}[\]\)]\s*$",
        r"субтитр\w*\s+(сделал|подготов|создав|редактор)",
        r"dimatorzok|amara\.org|subs?\s*by",
        r"продолжение следует",
        r"спасибо за (просмотр|внимание)\s*[!.]*\s*$",
        r"подпис\w+\s+на\s+канал",
        r"редактор субтитров",
    )
]


@dataclass
class Sentence:
    index: int
    text: str
    start: float
    end: float


def extract_audio(video: Path, target: Path,
                  log: Callable[[str], None]) -> Path:
    """16 kHz mono is what the model wants; anything else is resampled anyway."""
    ffmpeg = env.FFMPEG if env.FFMPEG.exists() else Path("ffmpeg")
    command = [str(ffmpeg), "-y", "-i", str(video),
               "-vn", "-ac", "1", "-ar", "16000",
               "-c:a", "pcm_s16le", "-loglevel", "error", str(target)]
    result = subprocess.run(command, capture_output=True, text=True,
                            encoding="utf-8", errors="replace",
                            creationflags=env.hide_console_flags())
    if result.returncode != 0 or not target.exists():
        raise RuntimeError(f"ffmpeg не смог прочитать файл: "
                           f"{(result.stderr or '').strip()[:300]}")
    log(f"Звуковая дорожка извлечена: {target.stat().st_size / 1e6:.0f} МБ")
    return target


def media_duration(path: Path) -> float:
    ffprobe = env.FFPROBE if env.FFPROBE.exists() else Path("ffprobe")
    try:
        result = subprocess.run(
            [str(ffprobe), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True,
            creationflags=env.hide_console_flags())
        return float(result.stdout.strip())
    except (ValueError, OSError, subprocess.SubprocessError):
        return 0.0


class Recogniser:
    """Loaded once and reused for the whole batch.

    Reloading the model per file costs roughly forty seconds each time, which
    on a batch of six films is four minutes of pure waiting.
    """

    def __init__(self, log: Callable[[str], None]) -> None:
        self.log = log
        self._model = None
        self._pipeline = None
        self.mode = ""
        self.batch_size = 1
        self.batched = False
        self.note = ""
        self.last_speed = 0.0

    def load(self) -> None:
        if self._model is not None:
            return

        env.enable_local_packages()
        from faster_whisper import WhisperModel

        info = gpu.detect()
        config = env.load_config()["recognition"]

        model_dir = self._model_dir()
        device = "cuda" if info.present else "cpu"
        compute = info.compute_type()

        try:
            self._model = WhisperModel(str(model_dir), device=device,
                                       compute_type=compute)
            self.mode = f"{'видеокарта' if info.present else 'процессор'} · {compute}"
        except Exception as exc:
            if device == "cpu":
                raise
            # Card present but CUDA libraries missing or broken. Falling back is
            # better than failing, but the user has to know it happened.
            self.log(f"Видеокарта недоступна ({str(exc)[:160]}). "
                     f"Переключаюсь на процессор — будет заметно медленнее.")
            self._model = WhisperModel(str(model_dir), device="cpu",
                                       compute_type="int8")
            self.mode = "процессор · int8 (аварийный режим)"

        batch = config.get("batch_size", "auto")
        batch = info.batch_size() if batch == "auto" else int(batch)
        if batch > 1:
            try:
                from faster_whisper import BatchedInferencePipeline
                self._pipeline = BatchedInferencePipeline(model=self._model)
                self.batch_size = batch
                self.batched = True
            except Exception as exc:
                # This is the single biggest speed factor, so a failure here is
                # reported rather than swallowed: without it the difference is
                # three or four times, and nothing on screen would explain why.
                self._pipeline = None
                self.note = f"пакетный режим недоступен: {str(exc)[:120]}"
                self.log(self.note)

        self.mode += (f" · пакет {self.batch_size}" if self.batched
                      else " · без пакета")
        self.log(f"Режим: {self.mode}")

    @staticmethod
    def _model_dir() -> Path:
        for name in ("large-v3", "medium"):
            candidate = env.MODELS / f"faster-whisper-{name}"
            if (candidate / "model.bin").exists():
                return candidate
        raise RuntimeError("Модель распознавания не установлена. "
                           "Откройте вкладку «Компоненты».")

    def transcribe(self, audio: Path, termbase: Termbase,
                   on_progress: Callable[[float], None]) -> list[Sentence]:
        self.load()
        config = env.load_config()["recognition"]
        total = media_duration(audio) or 1.0
        started = time.perf_counter()

        options = dict(
            language=config.get("language", "ru"),
            word_timestamps=bool(config.get("word_timestamps", True)),
            vad_filter=bool(config.get("vad", True)),
            vad_parameters={"min_silence_duration_ms": 400},
            initial_prompt=termbase.asr_prompt(),
            condition_on_previous_text=False,   # stops repetition loops
            beam_size=int(config.get("beam_size", 1)),
        )

        if self._pipeline is not None:
            call = self._pipeline.transcribe
            segments, _ = call(str(audio), batch_size=self.batch_size,
                               **_accepted(call, options))
        else:
            call = self._model.transcribe
            segments, _ = call(str(audio), **_accepted(call, options))

        words: list[tuple[str, float, float]] = []
        for segment in segments:
            on_progress(min(segment.end / total, 0.999))
            if segment.words:
                for word in segment.words:
                    token = word.word.strip()
                    if token:
                        words.append((token, word.start, word.end))
            elif segment.text.strip():
                # Word timestamps turned off: the segment itself becomes one
                # unit. Boundaries are coarser but the timing is still honest.
                words.append((segment.text.strip(), segment.start, segment.end))

        elapsed = max(time.perf_counter() - started, 0.01)
        self.last_speed = total / elapsed
        self.log(f"Скорость: {self.last_speed:.1f}x реального времени")

        on_progress(1.0)
        return self._to_sentences(words, termbase)

    # -- sentence assembly -------------------------------------------------- #

    @staticmethod
    def _to_sentences(words: list[tuple[str, float, float]],
                      termbase: Termbase) -> list[Sentence]:
        config = env.load_config()["sentences"]
        pause = float(config.get("pause_split", 0.7))
        max_chars = int(config.get("max_chars", 250))
        min_chars = int(config.get("min_chars", 30))

        sentences: list[Sentence] = []
        buffer: list[str] = []
        start = end = 0.0

        def flush() -> None:
            nonlocal buffer
            if not buffer:
                return
            text = " ".join(buffer)
            text = re.sub(r"\s+([,.!?;:…])", r"\1", text).strip()
            # The term base maps Russian to Romanian, so it must never be
            # applied here: it would turn the Russian transcript into a mixture
            # of two languages. Its Russian side helps earlier, as recogniser
            # context; its Romanian side is enforced later, on the translation.
            if text and not _is_noise(text):
                sentences.append(Sentence(len(sentences) + 1, text, start, end))
            buffer = []

        for position, (token, word_start, word_end) in enumerate(words):
            if not buffer:
                start = word_start
            buffer.append(token)
            end = word_end

            gap = (words[position + 1][1] - word_end
                   if position + 1 < len(words) else 99.0)
            length = len(" ".join(buffer))
            ends_sentence = (token.endswith((".", "!", "?", "…"))
                             and not _is_abbreviation(token))

            # Punctuation is the only reliable end of a thought. A silence is
            # not: narration in documentaries pauses for effect mid-sentence,
            # and splitting there produced captions reading just "На" or "Они".
            if ends_sentence:
                flush()
            elif gap >= pause and length >= min_chars:
                flush()
            elif length >= max_chars:
                flush()

        flush()
        sentences = _merge_fragments(sentences, min_chars, max_chars)
        for number, sentence in enumerate(sentences, 1):
            sentence.index = number
        return sentences


ABBREVIATIONS = {"т.", "г.", "гг.", "им.", "ул.", "тыс.", "млн.", "млрд.",
                 "проц.", "др.", "т.д.", "т.п.", "т.е."}


def _is_abbreviation(token: str) -> bool:
    lowered = token.lower()
    return lowered in ABBREVIATIONS or (len(lowered) <= 2 and lowered.endswith("."))


def _merge_fragments(sentences: list[Sentence], min_chars: int,
                     max_chars: int) -> list[Sentence]:
    """Glue back anything that is not a sentence on its own.

    Two signs of a fragment: it is very short, or it does not end on final
    punctuation. Either way the fix is the same — attach it to the neighbour it
    belongs to, and let the merged span cover both, so timing stays honest.
    """
    if not sentences:
        return sentences

    merged: list[Sentence] = []
    for sentence in sentences:
        text = sentence.text.strip()
        if not text:
            continue

        starts_lower = text[:1].islower()
        previous = merged[-1] if merged else None
        can_extend = (previous is not None
                      and len(previous.text) + len(text) + 1 <= max_chars)

        # A lowercase opening means the previous line was cut mid-thought.
        if can_extend and starts_lower and not previous.text.endswith((".", "!", "?", "…")):
            previous.text = f"{previous.text} {text}"
            previous.end = sentence.end
            continue

        # A stub too short to be a caption joins whatever came before it.
        if can_extend and len(text) < min_chars and not previous.text.endswith(("!", "?")):
            previous.text = f"{previous.text} {text}"
            previous.end = sentence.end
            continue

        merged.append(sentence)

    # A leading stub has no previous line, so it borrows the next one instead.
    while len(merged) > 1 and len(merged[0].text) < min_chars \
            and not merged[0].text.endswith((".", "!", "?", "…")):
        head, following = merged[0], merged[1]
        following.text = f"{head.text} {following.text}"
        following.start = head.start
        merged.pop(0)
    return merged


def _is_noise(text: str) -> bool:
    return any(pattern.search(text) for pattern in NOISE_PATTERNS)


def iter_media(folder: Path) -> Iterator[Path]:
    for item in sorted(folder.iterdir()):
        if item.is_file() and item.suffix.lower() in env.VIDEO_SUFFIXES:
            yield item


def _accepted(func, options: dict) -> dict:
    """Keep only the arguments this build actually takes.

    The batched and sequential paths do not accept the same set, and the set
    shifts between faster-whisper releases. Filtering by signature means a new
    version can never turn a working install into a crash.
    """
    try:
        parameters = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return options
    if any(p.kind is p.VAR_KEYWORD for p in parameters.values()):
        return options
    return {k: v for k, v in options.items() if k in parameters}
