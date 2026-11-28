"""Build the PeakSift starter library release from the downloaded source packs (maintainers).

    python scripts/build_library_release.py SOURCES OUT

``SOURCES`` holds the packs as downloaded (each from its own page, licence file included):

- ``kenney/x-<pack>/``: Kenney audio packs, CC0 (kenney.nl)
- ``oga/<slug>.<ext>`` + ``oga/sources.json``: CC0 music from OpenGameArt.org
- ``fluent/*.png`` + ``fluent/LICENSE`` + ``fluent/sources.json``: Microsoft Fluent Emoji, MIT

It picks the starter set below, converts every sound to Ogg Vorbis (loudness unchanged),
copies stickers as PNG, writes ``manifest.json`` (each file's sha256, licence and source) and
the licence files, and packs ``OUT/peaksift-library-<version>.tar.gz``. The archive is published
as a GitHub release; ``scripts/fetch_library.py`` installs it on servers (pinned sha256). Media
is never committed to the repository.
"""

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

VERSION = "library-v1"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

KENNEY = {"name": "Kenney", "url": "https://kenney.nl", "licence": "CC0-1.0"}
FLUENT = {
    "name": "Microsoft Fluent Emoji",
    "url": "https://github.com/microsoft/fluentui-emoji",
    "licence": "MIT",
}

# (pack, file stem pattern, how many, title, category, tags)
SFX = [
    ("interface-sounds", r"click_00[1-3]", 3, "Click", "interface", ["click", "tap"]),
    ("interface-sounds", r"drop_00[1-2]", 2, "Pop", "interface", ["pop", "drop"]),
    ("interface-sounds", r"tick_00[1-2]", 2, "Tick", "interface", ["tick", "clock"]),
    ("interface-sounds", r"switch_00[1-2]", 2, "Switch", "interface", ["switch", "toggle"]),
    ("interface-sounds", r"pluck_00[1-2]", 2, "Pluck", "interface", ["pluck"]),
    ("interface-sounds", r"confirmation_00[1-3]", 3, "Success", "alerts", ["success", "yes"]),
    ("interface-sounds", r"error_00[1-3]", 3, "Error", "alerts", ["error", "wrong", "no"]),
    ("interface-sounds", r"question_00[1-2]", 2, "Question", "alerts", ["question", "huh"]),
    ("interface-sounds", r"bong_001", 1, "Bong", "alerts", ["bong", "gong"]),
    ("interface-sounds", r"glass_00[1-2]", 2, "Glass ding", "alerts", ["ding", "glass"]),
    ("interface-sounds", r"glitch_00[1-4]", 4, "Glitch", "funny", ["glitch", "digital"]),
    ("interface-sounds", r"scratch_00[1-3]", 3, "Scratch", "funny", ["scratch", "record"]),
    ("interface-sounds", r"maximize_00[1-3]", 3, "Swoosh up", "transitions", ["swoosh", "up"]),
    ("interface-sounds", r"minimize_00[1-3]", 3, "Swoosh down", "transitions", ["swoosh"]),
    ("impact-sounds", r"impactPunch_heavy_00[0-2]", 3, "Punch", "hits", ["punch", "hit"]),
    ("impact-sounds", r"impactBell_heavy_00[0-1]", 2, "Bell hit", "hits", ["bell", "hit"]),
    ("impact-sounds", r"impactGlass_heavy_00[0-1]", 2, "Glass smash", "hits", ["glass", "smash"]),
    ("impact-sounds", r"impactMetal_heavy_00[0-1]", 2, "Metal hit", "hits", ["metal", "clang"]),
    ("impact-sounds", r"impactSoft_heavy_00[0-1]", 2, "Thud", "hits", ["thud", "fall"]),
    ("impact-sounds", r"impactWood_heavy_00[0-1]", 2, "Wood knock", "hits", ["knock", "wood"]),
    ("sci-fi-sounds", r"explosionCrunch_00[0-2]", 3, "Explosion", "hits", ["explosion", "boom"]),
    ("sci-fi-sounds", r"lowFrequency_explosion_00[0-1]", 2, "Deep boom", "hits", ["boom", "bass"]),
    ("sci-fi-sounds", r"forceField_00[0-1]", 2, "Shimmer", "transitions", ["shimmer", "magic"]),
    ("sci-fi-sounds", r"thrusterFire_00[0-1]", 2, "Whoosh", "transitions", ["whoosh", "rush"]),
    ("sci-fi-sounds", r"laserRetro_00[0-2]", 3, "Retro laser", "funny", ["laser", "retro"]),
    ("digital-audio", r"powerUp([1-3])", 3, "Power up", "funny", ["power up", "level up"]),
    ("digital-audio", r"phaserUp[1-2]", 2, "Rise", "transitions", ["rise", "riser"]),
    ("digital-audio", r"phaserDown[1-2]", 2, "Fall", "transitions", ["fall", "drop"]),
    ("digital-audio", r"zap[1-2]", 2, "Zap", "funny", ["zap"]),
    ("digital-audio", r"pepSound[1-3]", 3, "Blip", "funny", ["blip", "beep"]),
    ("digital-audio", r"threeTone[1-2]", 2, "Three tones", "alerts", ["tones", "notification"]),
    ("casino-audio", r"chips-collide-[1-2]", 2, "Coins", "money", ["coins", "money", "cash"]),
    ("casino-audio", r"card-slide-[1-2]", 2, "Swipe", "transitions", ["swipe", "slide"]),
    ("ui-audio", r"rollover[1-2]", 2, "Hover", "interface", ["hover", "soft"]),
]
JINGLES = [
    (r"jingles_SAX0[0-2]", 3, "Sax sting", ["sax", "funny", "sting"]),
    (r"jingles_HIT0[0-2]", 3, "Hit sting", ["hit", "sting", "reveal"]),
    (r"jingles_PIZZI0[0-1]", 2, "Pizzicato sting", ["pizzicato", "sneaky"]),
    (r"jingles_STEEL0[0-1]", 2, "Steel drum sting", ["steel drum", "happy"]),
]
MUSIC_MOOD = {
    "crystal-cave": ("Crystal Cave", "calm", ["ambient", "dreamy"]),
    "loading-screen-loop": ("Loading Loop", "chill", ["loop", "electronic"]),
    "field-of-dreams": ("The Field of Dreams", "cinematic", ["orchestral", "hopeful"]),
    "menu-music": ("Menu Music", "upbeat", ["electronic", "upbeat"]),
    "bossa-nova": ("8-bit Bossa", "chill", ["bossa", "retro"]),
    "next-to-you": ("Next to You", "chill", ["soft", "piano"]),
    "snowfall": ("Snowfall (loop)", "calm", ["soft", "winter"]),
    "tower-defense": ("Tower Defense Theme", "energetic", ["action", "game"]),
    "fast-fight": ("Fast Fight (loop)", "energetic", ["action", "battle", "loop"]),
    "i-swear-i-saw-it": ("I Swear I Saw It", "suspense", ["mystery", "tension"]),
    "happy-lullaby": ("Happy Lullaby", "playful", ["happy", "cute"]),
    "zombies-march": ("Zombies' March", "playful", ["funny", "spooky"]),
    "insistent": ("Insistent (loop)", "suspense", ["tension", "loop"]),
}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def duration(path: Path) -> float:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True, timeout=60,
    ).stdout  # fmt: skip
    return round(float(out.strip()), 3)


def to_ogg(source: Path, target: Path, quality: int, max_seconds: float | None = None) -> None:
    command = [FFMPEG, "-v", "error", "-y", "-i", str(source), "-vn", "-map_metadata", "-1"]
    if max_seconds:
        command += ["-t", f"{max_seconds}", "-af", f"afade=t=out:st={max_seconds - 2}:d=2"]
    command += ["-c:a", "libvorbis", "-q:a", str(quality), str(target)]
    subprocess.run(command, check=True, timeout=300)


def main(sources: Path, out: Path) -> int:
    root = out / VERSION
    shutil.rmtree(root, ignore_errors=True)
    for folder in ("sfx", "music", "stickers", "licences"):
        (root / folder).mkdir(parents=True)
    items: list[dict] = []

    def add(kind: str, file: Path, title: str, category: str, tags: list[str], source: dict,
            credit: str) -> None:  # fmt: skip
        item = {
            "id": file.stem,
            "kind": kind,
            "title": title,
            "category": category,
            "tags": tags,
            "file": f"{file.parent.name}/{file.name}",
            "sha256": sha256(file),
            "bytes": file.stat().st_size,
            "licence": source["licence"],
            "source": {"name": source["name"], "url": source["url"]},
            "credit": credit,
        }
        if kind in ("sfx", "music"):
            item["duration_seconds"] = duration(file)
        items.append(item)

    kenney = sources / "kenney"
    for pack, pattern, count, title, category, tags in SFX:
        found = sorted(
            p for p in (kenney / f"x-{pack}").rglob("*.ogg") if re.fullmatch(pattern, p.stem)
        )
        if len(found) < count:
            raise SystemExit(f"{pack}: expected {count} files for {pattern}, found {len(found)}")
        for number, path in enumerate(found[:count], start=1):
            label = title if count == 1 else f"{title} {number}"
            target = root / "sfx" / f"{slug(label)}.ogg"
            to_ogg(path, target, 4)
            add("sfx", target, label, category, tags, KENNEY, "Kenney (kenney.nl), CC0")
    for pattern, count, title, tags in JINGLES:
        found = sorted(
            p for p in (kenney / "x-music-jingles").rglob("*.ogg") if re.fullmatch(pattern, p.stem)
        )[:count]
        for number, path in enumerate(found, start=1):
            label = f"{title} {number}"
            target = root / "sfx" / f"{slug(label)}.ogg"
            to_ogg(path, target, 4)
            add("sfx", target, label, "stings", tags, KENNEY, "Kenney (kenney.nl), CC0")

    oga = json.loads((sources / "oga" / "sources.json").read_text())
    for entry in oga["items"]:
        title, mood, tags = MUSIC_MOOD[entry["slug"]]
        found = sorted((sources / "oga").glob(f"{entry['slug']}.*"))
        found = [p for p in found if p.suffix != ".json"]
        if not found:
            continue  # the source file could not be downloaded; the track is left out
        target = root / "music" / f"{entry['slug']}.ogg"
        to_ogg(found[0], target, 5, max_seconds=180 if duration(found[0]) > 180 else None)
        source = {"name": "OpenGameArt.org", "url": entry["page"], "licence": "CC0-1.0"}
        add("music", target, title, mood, tags, source,
            f"{entry['author']} on OpenGameArt.org, CC0")  # fmt: skip

    fluent = json.loads((sources / "fluent" / "sources.json").read_text())
    for entry in fluent["items"]:
        path = sources / "fluent" / entry["file"]
        if not path.is_file():
            continue
        target = root / "stickers" / f"{slug(entry['name'])}.png"
        shutil.copyfile(path, target)
        add("sticker", target, entry["name"], "emoji", [entry["name"].lower()], FLUENT,
            "Microsoft Fluent Emoji, MIT licence")  # fmt: skip
    shutil.copyfile(sources / "fluent" / "LICENSE", root / "licences" / "fluent-emoji-MIT.txt")
    kenney_licence = next((kenney / "x-interface-sounds").rglob("License.txt"))
    shutil.copyfile(kenney_licence, root / "licences" / "kenney-CC0.txt")
    (root / "licences" / "opengameart-CC0.txt").write_text(
        "The music tracks are dedicated to the public domain under CC0 1.0 by their authors on "
        "OpenGameArt.org (see each track's source page in manifest.json):\n"
        "https://creativecommons.org/publicdomain/zero/1.0/\n",
        encoding="utf-8",
    )
    manifest = {"version": VERSION, "items": items, "licences": sorted(
        f"licences/{p.name}" for p in (root / "licences").iterdir())}  # fmt: skip
    (root / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    archive = out / f"peaksift-{VERSION}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(root, arcname=VERSION)
    counts = {
        kind: sum(1 for i in items if i["kind"] == kind) for kind in ("sfx", "music", "sticker")
    }
    print(f"{archive.name}: {counts}, {archive.stat().st_size} bytes, sha256 {sha256(archive)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2])))
