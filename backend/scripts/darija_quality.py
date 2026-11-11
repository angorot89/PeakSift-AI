"""V1.8 Darija quality manual set: what PeakSift does with Darija, French, Arabic, English and
mixed speech, line by line, for a person to review (no model, no network, deterministic).

    python scripts/darija_quality.py            # a Markdown table
    python scripts/darija_quality.py --check    # exit 1 when a line's expectation is not met

Every line was written for this set (no quotations, no names of real people). For each line it
prints the language guess (always hedged), whether it can open a Short (``transcript_ideas``:
the line itself, never rewritten), and, for Darija, the other script by transliteration — the
only way PeakSift writes Darija, letter by letter, labelled "check the spelling". The
expectations below are the *automatic* part (language and whether an idea is offered); the
spelling column is for the reviewer: docs/morocco-mode.md records the review.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import hooks, language  # noqa: E402

# (line, expected language, an opening is offered)
LINES: list[tuple[str, str, bool]] = [
    # Darija in Latin letters (Arabizi), digits as letters.
    ("Wach 3mrk tfrjti f had l9hwa f Casablanca?", "darija", True),
    ("Lyoum ghadi nwerrikom kifach katsayb atay b na3na3.", "darija", True),
    ("Had lmakla zwina bzaf, walakin taman ghali chwiya.", "darija", True),
    ("Khouya, sber chwiya, rah kolchi ghadi ytsgad.", "darija", True),
    ("Chno katgolo, wach nzidou part 2?", "darija", True),
    # Darija in Arabic script.
    ("واش عمرك تفرجتي فهاد القهوة فكازا؟", "darija", True),
    ("اليوم غادي نوريكم كيفاش كنصاوبو أتاي بالنعناع.", "darija", True),
    ("هاد الماكلة زوينة بزاف ولكن الثمن غالي شوية.", "darija", True),
    # Mixed: Darija with French or English (code-switching).
    ("Wallah c'est incroyable, had lblasa zwina bzaf!", "mixed", True),
    ("Ana kanqra f la fac, mais kankhdem f weekend.", "mixed", True),
    ("Bro, had setup kayn fih kolchi, it's insane.", "mixed", True),
    # French, English, Modern Standard Arabic.
    ("Aujourd'hui je vous montre trois astuces pour filmer avec un téléphone.", "french", True),
    ("Here is the one tip nobody tells you about lighting.", "english", True),
    ("في هذا الفيديو سأشرح لكم ثلاث نصائح للتصوير بالهاتف.", "arabic", True),
    # Too short or not a sentence: no opening is offered.
    ("Salam.", "unknown", False),
    ("Ok ok.", "unknown", False),
]


def row(line: str) -> dict:
    guess = language.detect(line)
    ideas = hooks.transcript_ideas(line)
    other = ""
    if guess.language in ("darija", "mixed"):
        arabic = language.scripts(line) == ("arabic",)
        other = hooks.to_latin(line) if arabic else hooks.to_arabic(line)
    return {"guess": guess, "label": language.label(guess), "ideas": ideas, "other": other}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    misses = 0
    print("| Line | Detected | Opening offered | Other script (transliteration) | Expected |")
    print("|---|---|---|---|---|")
    for line, expected_language, expected_idea in LINES:
        r = row(line)
        lang_ok = r["guess"].language == expected_language
        idea_ok = bool(r["ideas"]) == expected_idea and all(i.text in line for i in r["ideas"])
        misses += not (lang_ok and idea_ok)
        offered = r["ideas"][0].kind if r["ideas"] else "—"
        mark = "✓" if lang_ok and idea_ok else f"✗ ({expected_language}, {expected_idea})"
        print(f"| {line} | {r['label']} | {offered} | {r['other'] or '—'} | {mark} |")
    print()
    print(f"{len(LINES) - misses}/{len(LINES)} lines as expected")
    return 1 if args.check and misses else 0


if __name__ == "__main__":
    sys.exit(main())
