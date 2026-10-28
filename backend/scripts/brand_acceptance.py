"""V1.7 release gate: a fully branded render and historical snapshot safety, against a running
PeakSift (real Auto Edit planner, real renders).

    BRAND_ACCEPTANCE_EMAIL=… BRAND_ACCEPTANCE_PASSWORD=… \\
        python scripts/brand_acceptance.py --api http://localhost:8000 \\
        --project <id> --video <id> --clip <id> --template <id> [--music <audio asset id>]

Signs in as a dedicated acceptance creator (credentials from the environment only) and:

1. plans the clip with the template (and the creator's music, if given), applies the plan and
   waits for the render; downloads it and checks 1080×1920 H.264 + AAC, the brand section the
   template asks for (logo when shown, end card when on), the duration (the clip plus the end
   card, exactly), loudness near the −14 LUFS mix target, and a silent end card;
2. changes the template (its caption style), reopens the rendered version and checks that its
   configuration and its file bytes are unchanged and its origin still names the old template
   version — then puts the template's settings back.

Prints each check and exits 1 when any fails.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

FFPROBE = os.environ.get("FFPROBE_PATH", "ffprobe")
FFMPEG = os.environ.get("FFMPEG_PATH", "ffmpeg")
failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'} {what}")
    if not ok:
        failures.append(what)


def wait(c: httpx.Client, path: str, done: tuple[str, ...], seconds: int = 1200) -> dict:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        body = c.get(path).json()
        if body.get("status") in done:
            return body
        if body.get("status") == "failed":
            raise SystemExit(f"{path} failed: {body.get('error_code')}")
        time.sleep(3)
    raise SystemExit(f"timed out waiting for {path}")


def probe(path: Path) -> dict:
    raw = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,codec_name,width,height", "-of", "json", str(path)],
        capture_output=True, text=True, check=True, timeout=60,
    ).stdout  # fmt: skip
    data = json.loads(raw)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), {})
    return {
        "duration": float(data["format"]["duration"]),
        "size": (video["width"], video["height"]),
        "video": video["codec_name"],
        "audio": audio.get("codec_name"),
    }


def lufs(path: Path, start: float | None = None, length: float | None = None) -> float | None:
    args = [FFMPEG, "-hide_banner", "-nostats"]
    if start is not None:
        args += ["-ss", f"{start:.2f}", "-t", f"{length:.2f}"]
    args += ["-i", str(path), "-af", "ebur128", "-f", "null", "-"]
    err = subprocess.run(args, capture_output=True, text=True, timeout=120).stderr
    found = re.search(r"I:\s+(-?[\d.]+) LUFS", err[err.rfind("Summary:") :])
    return float(found.group(1)) if found else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", default="http://localhost:8000")
    for name in ("project", "video", "clip", "template"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--music")
    args = parser.parse_args()
    email = os.environ.get("BRAND_ACCEPTANCE_EMAIL")
    password = os.environ.get("BRAND_ACCEPTANCE_PASSWORD")
    if not email or not password:
        print("Set BRAND_ACCEPTANCE_EMAIL and BRAND_ACCEPTANCE_PASSWORD.", file=sys.stderr)
        return 2
    c = httpx.Client(base_url=args.api, timeout=300)
    if c.post("/auth/login", json={"email": email, "password": password}).status_code != 200:
        print("Sign-in failed.", file=sys.stderr)
        return 2
    base = f"/projects/{args.project}/videos/{args.video}/clips/{args.clip}"
    template = c.get(f"/brand/templates/{args.template}").json()
    settings = template["config"]
    clip_seconds = c.get(f"/projects/{args.project}/videos/{args.video}/clips").json()
    clip_seconds = next(
        x["duration_seconds"] for x in clip_seconds["clips"] if x["id"] == args.clip
    )

    body = {"template_id": args.template, **({"music_asset_id": args.music} if args.music else {})}
    plan = c.post(f"{base}/auto-edits", json=body).json()
    # The same template version and inputs may return an earlier plan, already applied:
    # applying it again returns its version.
    plan = wait(c, f"{base}/auto-edits/{plan['id']}", ("ready", "applied"))
    check(
        plan["explanations"]["template"]["name"] == template["name"], "the plan used the template"
    )
    edit = c.post(f"{base}/auto-edits/{plan['id']}/apply").json()["edit"]
    edit = wait(c, f"{base}/edits/{edit['id']}", ("ready",))
    brand = edit["configuration"].get("brand") or {}
    with tempfile.TemporaryDirectory() as tmp:
        short = Path(tmp) / "short.mp4"
        short.write_bytes(c.get(f"/edits/{edit['id']}/download").content)
        digest = hashlib.sha256(short.read_bytes()).hexdigest()
        meta = probe(short)
        card = (brand.get("end_card") or {}).get("seconds", 0.0)
        check(meta["size"] == (1080, 1920) and meta["video"] == "h264", "1080×1920 H.264")
        check(meta["audio"] == "aac", "AAC audio")
        expected = clip_seconds + card
        check(
            abs(meta["duration"] - expected) <= 0.2,
            f"duration {meta['duration']:.2f}s = clip {clip_seconds:.2f}s + end card {card}s",
        )
        check(bool(brand) == bool(template["brand"]), "the brand section follows the template")
        if template["brand"] and template["brand"]["has_logo"]:
            check(("logo" in brand) == settings["logo"], "the logo follows the template")
        check(("end_card" in brand) == settings["end_card"], "the end card follows the template")
        mix = lufs(short)
        if (edit["configuration"].get("audio") or {}).get("normalize"):
            check(mix is not None and abs(mix + 14.0) <= 1.0, f"loudness {mix} LUFS (target −14)")
        if card:
            tail = lufs(short, clip_seconds + 0.3, card - 0.5)
            check(tail is not None and tail <= -60, f"the end card is silent ({tail} LUFS)")

        # Historical safety: change the template; the rendered version must not change.
        other = "minimal" if settings.get("caption_preset") != "minimal" else "focus"
        changed = c.patch(
            f"/brand/templates/{args.template}",
            json={"config": {**settings, "caption_preset": other}},
        )
        try:
            reopened = c.get(f"{base}/edits/{edit['id']}").json()
            again = Path(tmp) / "again.mp4"
            again.write_bytes(c.get(f"/edits/{edit['id']}/download").content)
            check(changed.json()["version"] > template["version"], "the template has a new version")
            check(
                reopened["configuration"] == edit["configuration"],
                "the old version's settings are unchanged",
            )
            check(
                hashlib.sha256(again.read_bytes()).hexdigest() == digest,
                "the old file is byte-identical",
            )
            made_with = edit["origin"]["template"]["version"]
            check(
                reopened["origin"]["template"]["version"] == made_with,
                "its origin still names the template version it was made with",
            )
        finally:
            c.patch(f"/brand/templates/{args.template}", json={"config": settings})
    print("BRAND ACCEPTANCE " + ("FAILED" if failures else "PASSED"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
