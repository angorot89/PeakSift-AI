"""Language intelligence for creators: what a transcript is likely in, and a matching-only
normalization that understands Darija in Arabic script and in Latin letters (Arabizi).

Conservative on purpose:

- ``detect`` reports a **likely** language with a confidence word (``likely`` / ``possible``)
  and the signals it saw, never a certainty; few words give ``unknown``. Code-switching (Darija
  with French or English) is a normal result (``mixed``), not malformed input. A creator's own
  choice (the project's content language) always wins over detection.
- ``fold`` / ``tokens`` exist only for **comparing** text (hook grounding, repeated phrases,
  search). They never rewrite what a creator said: transcripts and captions keep their original
  words, script and spelling.

The word lists are small, common function words and markers, not a dictionary; Darija shares
many words with Arabic and French, so detection weighs markers that are typical of Darija
(واش، ديال، بزاف، دابا… / wach, dyal, bzaf, daba…), Arabizi digits used as letters (3, 7, 9) and,
since the V1.8 quality set, Arabizi verbs with the ka- prefix ("kanqra", "katji").
"""

import re
import unicodedata
from dataclasses import dataclass, field

ARABIC_LETTER = re.compile(r"[ء-يٮ-ۓۺ-ۿ]")
LATIN_LETTER = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")
WORD = re.compile(r"[\w'’]+", re.UNICODE)
# Arabizi: Latin words that use 2, 3, 5, 7 or 9 as letters ("3lach", "7ta", "9alb", "sa7bi").
ARABIZI = re.compile(r"^(?=.*[a-z])(?=.*[23579])[a-z23579']+$")
# Darija verbs in Latin letters carry a ka- prefix with a person marker ("kanqra", "katji",
# "kaybghiw"): ka + n/t/y + a consonant. A marker like the others, never proof on its own.
DARIJA_VERB = re.compile(r"^ka[nty][bcdfghjklmnpqrstvwxz23579][a-z23579']+$")
ARABIC_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")

DARIJA_ARABIC = frozenset(
    "واش ديال ديالي ديالك ديالو بزاف دابا شنو شنا علاش غادي غاتي كاين كاينة مزيان مزيانة واخا "
    "صافي هادشي هادي هاد بغيت بغينا خويا زوين زوينة نتا نتي حيت ماشي فين كيفاش كيداير لا باس "
    "عافاك شحال بلا مكاينش عندي فهاد".split()
)  # fmt: skip
DARIJA_LATIN = frozenset(
    "wach wash dyal dial dyali dyalk bzaf bzzaf daba chno chnou chnu 3lach 3lash ghadi kayn kayen "
    "kayna mzyan mezyan wakha safi hadchi hadshi hadi had bghit bghina khoya zwin zwina nta nti "
    "hit machi fin kifach kifash kidayr labas 3afak ch7al bla makaynch 3ndi fhad 7ta 7tta kolchi "
    "koulchi chwiya chwia rah lyoum".split()
)  # fmt: skip
ARABIC_STANDARD = frozenset(
    "هذا هذه الذي التي الذين ليس سوف لقد إن أن هل لكن كان يكون نحن هم ذلك عندما".split()
)
FRENCH = frozenset(
    "le la les des une est c'est cest pas je tu nous vous avec pour très ça ca qui que dans sur "
    "mais donc parce voilà vraiment aussi tout".split()
)  # fmt: skip
ENGLISH = frozenset(
    "the and is are you this that with for what not was it's its have just like really because "
    "so they we".split()
)  # fmt: skip
MIN_WORDS = 4


@dataclass(frozen=True)
class LanguageGuess:
    """What a text is likely in. ``language``: darija, arabic, french, english, mixed or
    unknown; ``confidence``: likely or possible (never certain); ``scripts``: which writing
    systems appear; ``languages``: the languages seen in mixed text, strongest first."""

    language: str
    confidence: str
    scripts: tuple[str, ...]
    languages: tuple[str, ...] = ()
    signals: tuple[str, ...] = field(default_factory=tuple)

    def read(self) -> dict:
        return {
            "language": self.language,
            "confidence": self.confidence,
            "scripts": list(self.scripts),
            "languages": list(self.languages),
        }


def fold(text: str) -> str:
    """Lower-cased text for comparison only: Arabic diacritics and tatweel removed, alef, yaa and
    taa marbuta variants unified, Latin accents removed, letters repeated for emphasis collapsed
    ("bzzzaf" → "bzaf"). Digits stay (they are letters in Arabizi)."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = ARABIC_DIACRITICS.sub("", text)
    text = re.sub("[أإآٱ]", "ا", text).replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و")
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = text.replace("’", "'")
    return re.sub(r"([a-z])\1{2,}", r"\1", text)


def tokens(text: str) -> list[str]:
    """The folded words of ``text`` (for matching; never shown or stored)."""
    return [w.strip("'") for w in WORD.findall(fold(text)) if w.strip("'")]


def scripts(text: str) -> tuple[str, ...]:
    found = []
    if ARABIC_LETTER.search(text):
        found.append("arabic")
    if LATIN_LETTER.search(text):
        found.append("latin")
    return tuple(found)


def _folded(words: frozenset[str]) -> frozenset[str]:
    return frozenset(t for w in words for t in tokens(w))


_DARIJA = _folded(DARIJA_ARABIC) | _folded(DARIJA_LATIN)
_ARABIC = _folded(ARABIC_STANDARD)
_FRENCH = _folded(FRENCH)
_ENGLISH = _folded(ENGLISH)


def detect(text: str) -> LanguageGuess:
    """A conservative guess at what ``text`` is in (see the module docstring)."""
    words = tokens(text)
    found_scripts = scripts(text)
    if len(words) < MIN_WORDS:
        return LanguageGuess("unknown", "possible", found_scripts)
    counts = {
        "darija": sum(
            w in _DARIJA or bool(ARABIZI.match(w)) or bool(DARIJA_VERB.match(w)) for w in words
        ),
        "arabic": sum(w in _ARABIC for w in words),
        "french": sum(w in _FRENCH for w in words),
        "english": sum(w in _ENGLISH for w in words),
    }
    arabic_letters = len(ARABIC_LETTER.findall(text))
    latin_letters = len(LATIN_LETTER.findall(text))
    # Arabic script with no Darija marker reads as Arabic (standard or otherwise).
    if arabic_letters > latin_letters and counts["darija"] == 0:
        counts["arabic"] += max(1, len(words) // 6)
    ranked = sorted((n, lang) for lang, n in counts.items() if n > 0)[::-1]
    if not ranked:
        return LanguageGuess("unknown", "possible", found_scripts)
    total = sum(n for n, _ in ranked)
    present = tuple(lang for n, lang in ranked if n / total >= 0.25)
    signals = tuple(f"{lang}:{n}" for n, lang in ranked)
    if len(present) > 1:
        confidence = "likely" if total >= 4 else "possible"
        return LanguageGuess("mixed", confidence, found_scripts, present, signals)
    top_n, top = ranked[0]
    share = top_n / len(words)
    confidence = "likely" if top_n >= 3 and share >= 0.08 else "possible"
    return LanguageGuess(top, confidence, found_scripts, (top,), signals)


def label(guess: LanguageGuess) -> str:
    """ "Likely Darija", "Possibly French", "Likely mixed (Darija, French)" — never certain."""
    names = {"darija": "Darija", "arabic": "Arabic", "french": "French", "english": "English"}
    if guess.language == "unknown":
        return "Not enough speech to tell"
    prefix = "Likely" if guess.confidence == "likely" else "Possibly"
    if guess.language == "mixed":
        return f"{prefix} mixed ({', '.join(names[lang] for lang in guess.languages)})"
    return f"{prefix} {names[guess.language]}"
