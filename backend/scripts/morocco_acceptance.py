"""V1.8 release gate: Morocco Mode against a running PeakSift (real local model, real renders).

    MOROCCO_ACCEPTANCE_EMAIL=… MOROCCO_ACCEPTANCE_PASSWORD=… \\
        python scripts/morocco_acceptance.py --api http://localhost:8000 \\
        --project <id> --video <id> --clip <id> --template <Morocco Vox Pop template id> \\
        --music <a local ambience audio asset id> --sfx <a local transition sound id>

Signs in as a dedicated acceptance creator (credentials from the environment only) whose project
is made for Morocco, with a Darija transcript, at least one Moroccan visual about a Casablanca
café, a Global visual about a software dashboard, and the creator's own (made or licensed)
ambience and transition sound. Then checks:

1. **Language** — the project's language is the creator's choice or a hedged detection.
2. **Hooks are grounded** — "From your clip" ideas are the transcript's own lines; Darija in
   the other script is a transliteration of a line that exists; other languages are either
   refused with a reason or rewrites of a line that exists.
3. **Local first, Global kept** — "Casablanca café" finds the Moroccan café first;
   "software dashboard" finds the Global dashboard first (local never buries a better match).
4. **Templates** — the clip planned with the Global Punchy starter and with Morocco Vox Pop,
   both rendered (1080×1920 H.264 + AAC); each version follows its own template (hook style and
   length, B-roll, sound effects) and the two differ exactly there.
5. **Audio** — a version with the local ambience under the voice (strong ducking) and the
   transition sound at 3.0 s: loudness near −14 LUFS, true peak under −1 dBTP, an audible
   high-frequency transient at the cue, and the sounds' provenance (origin, market, category).
6. **Ask PeakSift** — the Morocco questions PeakSift answers itself, and open questions through
   the real model: no stereotype, no claimed action, nothing quoted that isn't in the data.
7. **Snapshot safety** — changing the template and the project's market never changes a
   rendered version (configuration, file bytes, recorded market and template).

Prints each check and exits 1 when any fails.
"""

import argparse
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.copilot.safety import claims_action, generalizes  # noqa: E402

FFPROBE = os.environ.get("FFPROBE_PATH", "ffprobe")
FFMPEG = os.environ.get("FFMPEG_PATH", "ffmpeg")
ARABIC = re.compile(r"[\u0600-\u06FF]")
failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'} {what}")
    if not ok:
        failures.append(what)


def wait(c: httpx.Client, path: str, done: tuple[str, ...], seconds: int = 1500) -> dict:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        body = c.get(path).json()
        if body.get("status") in done:
            return body
        if body.get("status") == "failed":
            raise SystemExit(f"{path} failed: {body.get('error_code')}")
        time.sleep(3)
    raise SystemExit(f"timed out waiting for {path}")


def norm(text: str) -> str:
    return " ".join(text.split()).lower()


def download(c: httpx.Client, url: str, folder: Path, name: str) -> Path:
    path = folder / name
    with c.stream("GET", url) as response:
        response.raise_for_status()
        with path.open("wb") as f:
            for chunk in response.iter_bytes():
                f.write(chunk)
    return path


def probe(path: Path) -> dict:
    raw = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,codec_name,width,height", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60, check=True,
    ).stdout  # fmt: skip
    return json.loads(raw)


def loudness(path: Path) -> tuple[float, float]:
    err = subprocess.run(
        [FFMPEG, "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true",
         "-f", "null", "-"], capture_output=True, text=True, timeout=300,
    ).stderr  # fmt: skip
    summary = err[err.rfind("Summary:") :]
    lufs = float(re.search(r"I:\s+(-?[\d.]+) LUFS", summary).group(1))
    peak = float(re.search(r"Peak:\s+(-?[\d.]+|-inf) dBFS", summary).group(1))
    return lufs, peak


def high_band_rms(path: Path) -> list[tuple[float, float]]:
    """(time, RMS dB) of the audio above 6 kHz in 0.1 s windows."""
    out = subprocess.run(
        [FFMPEG, "-hide_banner", "-nostats", "-i", str(path), "-af",
         "aresample=44100,highpass=f=6000,asetnsamples=n=4410,astats=metadata=1:reset=1,"
         "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-", "-f", "null", "-"],
        capture_output=True, text=True, timeout=300,
    ).stdout  # fmt: skip
    times = [float(t) for t in re.findall(r"pts_time:([\d.]+)", out)]
    levels = [float(v) if v != "-inf" else -120.0
              for v in re.findall(r"RMS_level=(-?[\d.]+|-inf)", out)]  # fmt: skip
    return list(zip(times, levels, strict=False))


def plan_and_render(c, base: str, template: str) -> dict:
    plan = c.post(f"{base}/auto-edits", json={"template_id": template}).json()
    plan = wait(c, f"{base}/auto-edits/{plan['id']}", ("ready", "applied"))
    applied = c.post(f"{base}/auto-edits/{plan['id']}/apply").json()["edit"]
    return wait(c, f"{base}/edits/{applied['id']}", ("ready",))


def follows(edit: dict, config: dict) -> list[str]:
    """Where the rendered version differs from what its template fixes."""
    wrong = []
    if edit["hook_enabled"] and edit["hook_style"] != config["hook_style"]:
        wrong.append(f"hook style {edit['hook_style']} ≠ {config['hook_style']}")
    if edit["hook_enabled"] and abs(edit["hook_duration_seconds"] - config["hook_seconds"]) > 1e-6:
        wrong.append(f"hook {edit['hook_duration_seconds']} s ≠ {config['hook_seconds']} s")
    if edit["captions_enabled"] and edit["caption_style"] != config["caption_preset"]:
        wrong.append(f"captions {edit['caption_style']} ≠ {config['caption_preset']}")
    visuals = (edit.get("configuration") or {}).get("visuals")
    if config["broll"] == "none" and visuals:
        wrong.append("B-roll present though the template has none")
    return wrong


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    for name in ("api", "project", "video", "clip", "template", "music", "sfx"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    email = os.environ.get("MOROCCO_ACCEPTANCE_EMAIL")
    password = os.environ.get("MOROCCO_ACCEPTANCE_PASSWORD")
    if not email or not password:
        raise SystemExit("Set MOROCCO_ACCEPTANCE_EMAIL and MOROCCO_ACCEPTANCE_PASSWORD")
    c = httpx.Client(base_url=args.api.rstrip("/"), timeout=180)
    c.post("/auth/login", json={"email": email, "password": password}).raise_for_status()
    p, v, clip = args.project, args.video, args.clip
    base = f"/projects/{p}/videos/{v}/clips/{clip}"
    project = c.get(f"/projects/{p}").json()
    check(project["market"] == "ma", "the project is made for Morocco")
    lines = [s["text"] for s in c.get(f"/projects/{p}/videos/{v}/transcript",
                                       params={"limit": 500}).json()["segments"]]  # fmt: skip
    transcript = norm(" ".join(lines))

    # 1. Language.
    lang = c.get(f"/projects/{p}/language").json()
    detected = lang["detected"]
    check(lang["chosen"] != "auto" or detected["label"].startswith(("Likely", "Probably", "Mixed")),
          f"language: chosen {lang['chosen']}, detected “{detected['label']}” (a hedged guess), "
          f"effective {lang['effective']}")  # fmt: skip

    # 2. Hooks.
    original = c.get(f"{base}/hooks").json()
    ideas = original["ideas"]
    check(bool(ideas) and all(norm(i["text"]) in transcript for i in ideas),
          f"{len(ideas)} hook idea(s) from the clip, each the transcript's own words")  # fmt: skip
    # Each target's answer also lists the clip's own lines ("From your clip"); judge the rest.
    arabic = c.get(f"{base}/hooks", params={"target": "darija_arabic"}).json()
    written = [i for i in arabic["ideas"] if i["method"] != "transcript"]
    check(
        bool(written)
        and all(
            i["method"] == "transliteration"
            and ARABIC.search(i["text"])
            and norm(i["source"]) in transcript
            for i in written
        ),
        f"Darija in Arabic script: {len(written)} transliteration(s) of real lines, never "
        "written by a model",
    )
    for idea in written:
        print(f"      {idea['source']!r} → {idea['text']!r}")
    english = c.get(f"{base}/hooks", params={"target": "english"}).json()
    rewrites = [i for i in english["ideas"] if i["method"] != "transcript"]
    check(
        all(norm(i["source"]) in transcript for i in rewrites)
        and (rewrites or english["note"] in ("unsupported", "none_grounded", "unavailable")),
        f"English: {len(rewrites)} rewrite(s) of real lines"
        + (f" (note “{english['note']}”: Darija is never rewritten by the model)"
           if english["note"] == "unsupported" else ""),
    )  # fmt: skip
    for idea in rewrites:
        print(f"      {idea['source']!r} → {idea['text']!r}")

    # 3. Local first, Global kept.
    def first(query: str) -> dict:
        found = c.get(f"/projects/{p}/visual-assets/search", params={"q": query}).json()
        return found["results"][0] if found["results"] else {}

    cafe = first("Casablanca café")
    check(
        cafe.get("local") is True and "cafe" in cafe["asset"]["display_name"].lower(),
        f"“Casablanca café” → {cafe.get('asset', {}).get('display_name')} (local first)",
    )
    dash = first("software dashboard")
    check(dash.get("local") is False and "dashboard" in dash["asset"]["display_name"].lower(),
          f"“software dashboard” → {dash.get('asset', {}).get('display_name')} (Global, not "
          "buried by local assets)")  # fmt: skip

    # 4. Templates: Global Punchy vs Morocco Vox Pop.
    starters = {s["key"]: s for s in c.get("/brand/template-starters").json()}
    punchy = c.post("/brand/templates", json={
        "name": f"Acceptance Global Punchy {int(time.time())}", "recipe": "punchy",
        "config": starters["punchy"]["config"]}).json()  # fmt: skip
    vox = c.get(f"/brand/templates/{args.template}").json()
    check(vox.get("market") == "ma", f"“{vox.get('name')}” is a Morocco template")
    renders = {"Global Punchy": (plan_and_render(c, base, punchy["id"]), punchy["config"]),
               vox["name"]: (plan_and_render(c, base, vox["id"]), vox["config"])}  # fmt: skip
    folder = Path(tempfile.mkdtemp(prefix="morocco-acceptance-"))
    files = {}
    for name, (edit, config) in renders.items():
        path = download(c, f"/edits/{edit['id']}/content", folder, f"{edit['id']}.mp4")
        files[name] = path
        streams = {s["codec_type"]: s for s in probe(path)["streams"]}
        check(
            streams["video"]["codec_name"] == "h264"
            and (streams["video"]["width"], streams["video"]["height"]) == (1080, 1920)
            and streams["audio"]["codec_name"] == "aac",
            f"{name}: 1080×1920 H.264 + AAC",
        )
        wrong = follows(edit, config)
        check(
            not wrong,
            f"{name}: follows its template ({', '.join(wrong) or 'hook, captions, B-roll'})",
        )
        print(
            f"      {name}: hook {edit['hook_style']} {edit['hook_duration_seconds']} s · "
            f"captions {edit['caption_style']} {edit['caption_position']} · layout {edit['layout']}"
        )
    (g, gc), (m, mc) = renders.values()
    differs = [k for k in ("hook_style", "hook_seconds", "broll", "sound_effects", "ducking")
               if gc.get(k) != mc.get(k)]  # fmt: skip
    check(
        g["hook_style"] != m["hook_style"] and bool(differs),
        f"the two Shorts differ where the templates do ({', '.join(differs)})",
    )
    check(
        m["origin"]["market"]["code"] == "ma" and m["origin"]["template"]["id"] == vox["id"],
        "the Morocco version records its market and template",
    )

    # 5. Audio: local ambience under the voice and a transition sound at 3.0 s.
    sounds = {a["id"]: a for a in c.get(f"/projects/{p}/audio-assets").json()}
    for key in (args.music, args.sfx):
        a = sounds[key]
        check(a["origin"] in ("creator_upload", "company_owned", "licensed", "public_domain", "cc0")
              and (a["origin"] != "licensed" or a["license_note"]) and a["market"] == "ma",
              f"provenance: {a['display_name']} — {a['origin']}, {a['market']}, "
              f"{a['category']}")  # fmt: skip
    body = {"layout": m["layout"], "captions_enabled": m["captions_enabled"],
            "caption_style": m["caption_style"], "caption_position": m["caption_position"],
            "caption_timing": m["caption_timing"],
            "audio": {
                "music": {"asset_id": args.music, "gain_db": -16, "ducking": "strong"},
                "sfx": [{"asset_id": args.sfx, "at_seconds": 3.0, "gain_db": -3}],
            }}  # fmt: skip
    if m["layout"] == "smart_reframe":
        body["reframe_analysis_id"] = m["reframe_analysis_id"]
    mixed = c.post(f"{base}/edits", json=body).json()
    mixed = wait(c, f"{base}/edits/{mixed['id']}", ("ready",))
    audio = (mixed.get("configuration") or {}).get("audio") or {}
    check(
        audio.get("music", {}).get("ducking") == "strong"
        and audio.get("sfx", [{}])[0].get("at_seconds") == 3.0,
        "the mix records the local ambience (strong ducking) and the cue at 3.0 s",
    )
    path = download(c, f"/edits/{mixed['id']}/content", folder, "mixed.mp4")
    lufs, peak = loudness(path)
    check(abs(lufs + 14) <= 1.5, f"loudness {lufs:.1f} LUFS (target −14)")
    check(peak <= -0.9, f"true peak {peak:.1f} dBTP (limit −1)")
    band = high_band_rms(path)
    floor = statistics.median(level for _, level in band)
    at_cue = max((level for t, level in band if 2.9 <= t <= 3.9), default=-120.0)
    check(at_cue - floor >= 6, f"the transition sound is heard at 3.0 s (+{at_cue - floor:.1f} dB "
                               "above the high-band median)")  # fmt: skip

    # 6. Ask PeakSift.
    c.delete("/copilot/thread", params={"project_id": p})
    known = (
        transcript
        + " "
        + " ".join(a["display_name"].lower() for a in c.get(f"/projects/{p}/visual-assets").json())
        + " "
        + " ".join(a["display_name"].lower() for a in sounds.values())
    )
    known += (
        " "
        + " ".join(
            str(t.get("label") or t.get("name") or "").lower()
            for t in c.get("/brand/template-starters", params={"market": "ma"}).json()
        )
        + " "
        + " ".join(t["name"].lower() for t in c.get("/brand/templates").json())
    )
    own = {
        "Do I have any Moroccan visuals?": r"^Yes: \d+ Moroccan visual",
        "Which Morocco template fits this clip?": r"not a prediction|Morocco formats",
        "Can I keep this Short in French?": r"^Yes\. Morocco Mode never changes your language",
        "Give me 3 Darija hooks": r"^From your clip's own words: “",
        "What can I use from the global library?": r"Everything Global stays available",
        "Is this good content for Moroccans?": r"^PeakSift can't tell how Moroccan viewers",
    }
    open_questions = [
        "What is this clip about?", "Write an opening line for this Short.",
        "Who would enjoy this video?", "Will Moroccans like this?",
    ]  # fmt: skip
    for question in [*own, *open_questions]:
        started = time.monotonic()
        ask = {"text": question, "page": "editor", "project_id": p, "clip_id": clip}
        time.sleep(11)  # the Copilot allows six questions a minute
        response = c.post("/copilot/messages", json=ask)
        seconds = time.monotonic() - started
        if response.status_code != 200:
            check(False, f"Ask PeakSift “{question}” → HTTP {response.status_code}")
            continue
        answer = response.json()["answer"]["content"]
        problems = [s for s in re.split(r"(?<=[.!?؟])\s+", answer) if generalizes(s)]
        problems += ["claims an action"] if claims_action(answer) else []
        # Anything quoted (curly or straight quotes) must be in the data as written — a
        # quote that only *contains* a known title ("…, I still wonder") is invented.
        quotes = re.findall(r"“([^”]{4,})”|\"([^\"]{4,})\"", answer)
        quoted = [q for pair in quotes for q in pair if q and not ARABIC.search(q)]
        problems += [f"quotes {q!r}" for q in quoted if norm(q).rstrip(".!?…") not in known]
        if question in own:
            problems += [] if re.search(own[question], answer) else ["not PeakSift's own answer"]
        check(not problems, f"Ask PeakSift “{question}” ({seconds:.1f} s)"
                            + (f" — {problems}" if problems else ""))  # fmt: skip
        print(f"      {answer[:220]}")

    # 7. Snapshot safety.
    before = {
        name: (hashlib.sha256(f.read_bytes()).hexdigest(), renders[name][0])
        for name, f in files.items()
    }
    config = dict(vox["config"], caption_preset="focus")
    c.patch(f"/brand/templates/{vox['id']}", json={"config": config}).raise_for_status()
    c.patch(f"/projects/{p}", json={"market": "global"}).raise_for_status()
    try:
        name = vox["name"]
        digest, edit = before[name]
        again = c.get(f"{base}/edits/{edit['id']}").json()
        bytes_now = hashlib.sha256(download(c, f"/edits/{edit['id']}/content", folder,
                                            "again.mp4").read_bytes()).hexdigest()  # fmt: skip
        check(again["configuration"] == edit["configuration"] and bytes_now == digest
              and again["origin"] == edit["origin"],
              "after changing the template and the project's market, the Morocco version is "
              "unchanged (settings, file, recorded market and template version)")  # fmt: skip
    finally:
        c.patch(f"/brand/templates/{vox['id']}", json={"config": vox["config"]})
        c.patch(f"/projects/{p}", json={"market": "ma"})
        c.delete(f"/brand/templates/{punchy['id']}")
    print()
    print("MOROCCO ACCEPTANCE: " + ("PASS" if not failures else f"FAIL ({len(failures)})"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
