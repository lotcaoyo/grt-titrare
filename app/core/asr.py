"""Speech recognition and sentence assembly.

Timing is decided here and nowhere else. Every subtitle later inherits the time
span of the Russian sentence it came from, so a longer Romanian translation can
never push the timecodes out of sync with the picture.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
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
                self.log(f"Режим: {self.mode}, пакет {batch}")
                return
            except Exception:
                self._pipeline = None
        self.batch_size = 1
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

        options = dict(
            language=config.get("language", "ru"),
            word_timestamps=True,
            vad_filter=bool(config.get("vad", True)),
            vad_parameters={"min_silence_duration_ms": 400},
            initial_prompt=termbase.asr_prompt(),
            condition_on_previous_text=False,   # stops repetition loops
            beam_size=int(config.get("beam_size", 5)),
        )

        if self._pipeline is not None:
            segments, _ = self._pipeline.transcribe(
                str(audio), batch_size=self.batch_size, **options)
        else:
            segments, _ = self._model.transcribe(str(audio), **options)

        words: list[tuple[str, float, float]] = []
        for segment in segments:
            on_progress(min(segment.end / total, 0.999))
            for word in (segment.words or []):
                token = word.word.strip()
                if token:
                    words.append((token, word.start, word.end))

        on_progress(1.0)
        return self._to_sentences(words, termbase)

    # -- sentence assembly -------------------------------------------------- #

    @staticmethod
    def _to_sentences(words: list[tuple[str, float, float]],
                      termbase: Termbase) -> list[Sentence]:
        config = env.load_config()["sentences"]
        pause = float(config.get("pause_split", 0.7))
        max_chars = int(config.get("max_chars", 250))

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
            ends_sentence = token.endswith((".", "!", "?", "…"))
            too_long = len(" ".join(buffer)) >= max_chars

            if (ends_sentence and gap >= 0.15) or gap >= pause or too_long:
                flush()

        flush()
        for number, sentence in enumerate(sentences, 1):
            sentence.index = number
        return sentences


def _is_noise(text: str) -> bool:
    return any(pattern.search(text) for pattern in NOISE_PATTERNS)


def iter_media(folder: Path) -> Iterator[Path]:
    for item in sorted(folder.iterdir()):
        if item.is_file() and item.suffix.lower() in env.VIDEO_SUFFIXES:
            yield item
