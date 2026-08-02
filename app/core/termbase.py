"""Bilingual term base.

Each entry works twice. The Russian side is fed to the recogniser as context,
which makes it far likelier to spell a name correctly the first time. The
Romanian side is applied to the finished translation, which guarantees the
canonical form regardless of what came back from the translator.

This file is the difference between a predictable result and a lottery.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from . import env

SECTIONS = ("people", "places", "organisations", "terms")

# Romanian is written with comma-below diacritics. Fonts and keyboards often
# produce the Turkish cedilla forms instead; Premiere renders them as tofu.
CEDILLA_FIX = {
    "\u015f": "\u0219", "\u015e": "\u0218",   # ş Ş -> ș Ș
    "\u0163": "\u021b", "\u0162": "\u021a",   # ţ Ţ -> ț Ț
}

TYPOGRAPHY = {
    "\u201c": "\u201e", "\u201d": "\u201d",   # normalise quotation marks
    "\u2018": "\u201e", "\u2019": "\u2019",
    "--": "\u2013",
    "\u00a0": " ",
}


class Termbase:
    def __init__(self, pairs: dict[str, str]) -> None:
        self.pairs = pairs
        self._enforcers = []
        seen: set[str] = set()
        for target in pairs.values():
            plain = _strip_diacritics(target)
            if plain == target or plain in seen or len(plain) < 4:
                continue
            seen.add(plain)
            # Diacritics live in the stem, endings do not. Capturing the ending
            # and putting it back restores inflected forms too: Gagauziei
            # becomes Găgăuziei, not Găgăuzia.
            # Romanian inflects by changing the final vowel, so the match is
            # made on the stem without it: Gagauziei becomes Găgăuziei rather
            # than being missed for not matching Gagauzia exactly.
            stem, canonical = plain, target
            if len(plain) > 5 and plain[-1].lower() in "aeiou":
                stem, canonical = plain[:-1], target[:-1]
            self._enforcers.append(
                (re.compile(rf"\b{re.escape(stem)}(\w*)"),
                 canonical.replace("\\", "\\\\") + r"\1"))

    # -- loading ----------------------------------------------------------- #

    @classmethod
    def load(cls) -> "Termbase":
        pairs: dict[str, str] = {}
        config = env.load_config()

        shared = str(config.get("termbase", {}).get("shared_path", "") or "")
        for source in (env.TERMBASE_FILE, Path(shared) if shared else None):
            if source and source.exists():
                pairs.update(cls._read(source))
        return cls(pairs)

    @staticmethod
    def _read(path: Path) -> dict[str, str]:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
        collected: dict[str, str] = {}
        for section in SECTIONS:
            entries = raw.get(section) or {}
            if isinstance(entries, dict):
                for source, target in entries.items():
                    if source and target:
                        collected[str(source).strip()] = str(target).strip()
        return collected

    # -- use --------------------------------------------------------------- #

    def asr_prompt(self, limit: int = 180) -> str:
        """Context handed to the recogniser before it hears the first word."""
        names = list(self.pairs.keys())[:limit]
        if not names:
            return "Новости Гагаузии, Комрат, Молдова."
        return ("Новостной репортаж. В тексте встречаются имена и названия: "
                + ", ".join(names) + ".")

    def enforce(self, text: str) -> str:
        """Restore canonical Romanian spelling of names in a translation.

        Translators reliably drop diacritics on proper nouns — Gagauzia for
        Găgăuzia, Chisinau for Chișinău. Each canonical form is matched through
        its stripped variant, so the correct spelling is put back automatically.
        """
        for pattern, target in self._enforcers:
            text = pattern.sub(target, text)
        return text

    def translation_reference(self, text: str) -> dict[str, str]:
        """Only the entries actually present, so the prompt stays short.

        Matching is done on word stems because Russian inflects: the base form
        "Народное собрание" has to be found inside "Народного собрания".
        """
        lowered = text.lower()
        found: dict[str, str] = {}
        for source, target in self.pairs.items():
            if all(stem in lowered for stem in _stems(source)):
                found[source] = target
        return found


def normalise_romanian(text: str) -> str:
    for wrong, right in CEDILLA_FIX.items():
        text = text.replace(wrong, right)
    for wrong, right in TYPOGRAPHY.items():
        text = text.replace(wrong, right)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return text.strip()


DIACRITIC_MAP = str.maketrans({
    "ă": "a", "Ă": "A", "â": "a", "Â": "A", "î": "i", "Î": "I",
    "ș": "s", "Ș": "S", "ț": "t", "Ț": "T",
})


def _strip_diacritics(text: str) -> str:
    return text.translate(DIACRITIC_MAP)


def _stems(phrase: str) -> list[str]:
    """Crude Russian stemming: enough to survive case endings."""
    stems = []
    for word in re.findall(r"\w+", phrase.lower()):
        stems.append(word[:-2] if len(word) >= 6 else word)
    return stems
