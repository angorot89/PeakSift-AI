"""Make the library's animated overlays (maintainers): transparent WebM clips.

    python scripts/build_overlays.py PARTICLES OUT

``PARTICLES`` is Kenney's Particle Pack ``PNG (Transparent)`` folder (CC0, kenney.nl): white
sprites made to be tinted. Every effect is drawn frame by frame with Pillow from those sprites
and plain shapes (deterministic: fixed seeds), then encoded with FFmpeg as VP9 with an alpha
channel (WebM, 720 × 1280, 30 fps). The result is CC0 like its sources. Nothing here runs in
the app; ``build_library_release.py`` adds the clips to the library.
"""

import json
import math
import random
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

W, H, FPS = 720, 1280, 30
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


def sprite(
    folder: Path, name: str, size: int, colour: tuple[int, int, int], solid: bool = False
) -> Image.Image:
    """A particle sprite scaled to ``size`` and tinted (the sprites are white on transparent).
    ``solid`` fills the shape with the colour through its own alpha (bright, for flames)."""
    image = Image.open(folder / f"{name}.png").convert("RGBA")
    image = image.resize((size, size), Image.Resampling.LANCZOS)
    if solid:
        filled = Image.new("RGBA", image.size, (*colour, 255))
        filled.putalpha(image.getchannel("A"))
        return filled
    tint = Image.new("RGBA", image.size, (*colour, 255))
    rgb = ImageChops.multiply(image, tint)
    rgb.putalpha(image.getchannel("A"))
    return rgb


def place(
    canvas: Image.Image,
    image: Image.Image,
    x: float,
    y: float,
    alpha: float = 1.0,
    angle: float = 0.0,
    scale: float = 1.0,
) -> None:
    if alpha <= 0.01 or scale <= 0.01:
        return
    if scale != 1.0:
        size = max(1, int(image.width * scale)), max(1, int(image.height * scale))
        image = image.resize(size, Image.Resampling.BILINEAR)
    if angle:
        image = image.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    if alpha < 1.0:
        image = image.copy()
        image.putalpha(image.getchannel("A").point(lambda v: int(v * alpha)))
    canvas.alpha_composite(image, (int(x - image.width / 2), int(y - image.height / 2)))


def ease_out(t: float) -> float:
    return 1 - (1 - min(max(t, 0.0), 1.0)) ** 3


# --- the effects (each returns the frame at time t, an RGBA image of W × H) -----------------------


def confetti(_folder: Path) -> tuple[float, Callable[[float], Image.Image]]:
    rng = random.Random(7)
    colours = [
        (255, 77, 109),
        (255, 209, 59),
        (65, 202, 255),
        (124, 252, 90),
        (180, 110, 255),
        (255, 140, 40),
    ]
    pieces = [
        dict(
            x=rng.uniform(0, W),
            y=rng.uniform(-H * 1.2, -20),
            vy=rng.uniform(360, 620),
            sway=rng.uniform(20, 60),
            phase=rng.uniform(0, 6.28),
            spin=rng.uniform(-400, 400),
            w=rng.uniform(10, 18),
            h=rng.uniform(18, 30),
            c=rng.choice(colours),
        )
        for _ in range(240)
    ]

    def frame(t: float) -> Image.Image:
        canvas = Image.new("RGBA", (W, H))
        draw = ImageDraw.Draw(canvas)
        for p in pieces:
            y = p["y"] + p["vy"] * t
            x = p["x"] + math.sin(p["phase"] + t * 4) * p["sway"]
            a = math.radians(p["spin"] * t)
            flip = abs(math.cos(p["phase"] + t * 6))  # tumbling: the piece narrows as it turns
            hw, hh = p["w"] * (0.3 + 0.7 * flip) / 2, p["h"] / 2
            pts = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
            rot = [
                (x + px * math.cos(a) - py * math.sin(a), y + px * math.sin(a) + py * math.cos(a))
                for px, py in pts
            ]
            draw.polygon(rot, fill=(*p["c"], 255))
        return canvas

    return 3.0, frame


def sparkle_burst(folder: Path) -> tuple[float, Callable[[float], Image.Image]]:
    rng = random.Random(3)
    stars = [sprite(folder, f"star_0{i}", 120, (255, 214, 90)) for i in (4, 6, 8)]
    parts = [
        dict(
            a=rng.uniform(0, 6.28),
            d=rng.uniform(180, 420),
            s=rng.choice(stars),
            delay=rng.uniform(0, 0.15),
            spin=rng.uniform(-200, 200),
        )
        for _ in range(22)
    ]
    glow = sprite(folder, "light_01", 520, (255, 236, 170))

    def frame(t: float) -> Image.Image:
        canvas = Image.new("RGBA", (W, H))
        place(canvas, glow, W / 2, H / 2, alpha=max(0.0, 0.9 - t * 1.6), scale=0.6 + t)
        for p in parts:
            k = (t - p["delay"]) / 1.2
            if k <= 0:
                continue
            r = ease_out(k) * p["d"]
            place(
                canvas,
                p["s"],
                W / 2 + math.cos(p["a"]) * r,
                H / 2 + math.sin(p["a"]) * r,
                alpha=1 - k,
                angle=p["spin"] * t,
                scale=0.5 + 0.7 * (1 - k),
            )
        return canvas

    return 1.5, frame


def fire(folder: Path) -> tuple[float, Callable[[float], Image.Image]]:
    rng = random.Random(11)
    flames = [
        sprite(folder, f"flame_0{i}", 280, c, solid=True)
        for i in (1, 2, 3, 4)
        for c in ((255, 150, 30), (255, 200, 60), (255, 100, 20))
    ]
    cores = [sprite(folder, f"flame_0{i}", 150, (255, 240, 160), solid=True) for i in (2, 5)]
    parts = [
        dict(
            x=rng.uniform(-40, W + 40),
            t0=rng.uniform(0, 2.0),
            life=rng.uniform(0.6, 1.0),
            s=rng.choice(flames),
            rise=rng.uniform(260, 480),
            wob=rng.uniform(0, 6.28),
        )
        for _ in range(90)
    ]
    parts += [
        dict(
            x=rng.uniform(0, W),
            t0=rng.uniform(0, 2.0),
            life=rng.uniform(0.4, 0.7),
            s=rng.choice(cores),
            rise=rng.uniform(160, 300),
            wob=rng.uniform(0, 6.28),
        )
        for _ in range(40)
    ]
    loop = 2.0
    glow = Image.new("RGBA", (W, H))
    shade = ImageDraw.Draw(glow)
    for row in range(320):  # a warm glow along the bottom edge
        shade.line(
            [(0, H - row), (W, H - row)], fill=(255, 120, 30, int(150 * (1 - row / 320) ** 2))
        )

    def frame(t: float) -> Image.Image:
        canvas = glow.copy()
        for p in parts:
            k = ((t - p["t0"]) % loop) / p["life"]
            if k >= 1:
                continue
            y = H + 40 - p["rise"] * k
            x = p["x"] + math.sin(p["wob"] + k * 5) * 18
            place(
                canvas,
                p["s"],
                x,
                y,
                alpha=min(1.0, math.sin(math.pi * k) * 1.5),
                scale=1.1 - 0.6 * k,
            )
        return canvas

    return loop, frame


def smoke_puff(folder: Path) -> tuple[float, Callable[[float], Image.Image]]:
    rng = random.Random(5)
    smokes = [sprite(folder, f"smoke_0{i}", 300, (235, 235, 240)) for i in (1, 3, 5, 7)]
    parts = [
        dict(
            a=rng.uniform(0, 6.28),
            d=rng.uniform(60, 260),
            s=rng.choice(smokes),
            spin=rng.uniform(-60, 60),
        )
        for _ in range(16)
    ]

    def frame(t: float) -> Image.Image:
        canvas = Image.new("RGBA", (W, H))
        k = t / 1.8
        for p in parts:
            r = ease_out(k) * p["d"]
            place(
                canvas,
                p["s"],
                W / 2 + math.cos(p["a"]) * r,
                H / 2 + math.sin(p["a"]) * r,
                alpha=0.85 * (1 - k),
                angle=p["spin"] * t,
                scale=0.6 + 1.1 * ease_out(k),
            )
        return canvas

    return 1.8, frame


def flash(_folder: Path) -> tuple[float, Callable[[float], Image.Image]]:
    # Brightest in the middle: a radial alpha ramp, scaled by the flash's envelope.
    ramp = Image.new("L", (W, H))
    pixels = ramp.load()
    reach = math.hypot(W / 2, H / 2)
    for y in range(0, H):
        for x in range(0, W):
            pixels[x, y] = int(255 - 70 * math.hypot(x - W / 2, y - H / 2) / reach)

    def frame(t: float) -> Image.Image:
        peak = min(t / 0.06, 1.0) if t < 0.06 else max(0.0, 1 - (t - 0.06) / 0.5) ** 1.5
        canvas = Image.new("RGBA", (W, H), (255, 255, 255, 0))
        canvas.putalpha(ramp.point(lambda v: int(v * peak)))
        return canvas

    return 0.6, frame


def hearts(_folder: Path) -> tuple[float, Callable[[float], Image.Image]]:
    rng = random.Random(9)

    def heart(size: int, colour: tuple[int, int, int]) -> Image.Image:
        big = size * 4
        image = Image.new("RGBA", (big, big))
        draw = ImageDraw.Draw(image)
        pts = []
        for i in range(120):
            a = math.tau * i / 120
            x = 16 * math.sin(a) ** 3
            y = 13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a) - math.cos(4 * a)
            pts.append((big / 2 + x * big / 36, big / 2 - y * big / 36))
        draw.polygon(pts, fill=(*colour, 255))
        return image.resize((size, size), Image.Resampling.LANCZOS)

    shapes = [
        heart(s, c) for s in (70, 100) for c in ((255, 60, 90), (255, 110, 160), (230, 30, 60))
    ]
    parts = [
        dict(
            x=rng.uniform(60, W - 60),
            t0=rng.uniform(0, 2.2),
            s=rng.choice(shapes),
            speed=rng.uniform(380, 560),
            wob=rng.uniform(0, 6.28),
        )
        for _ in range(26)
    ]

    def frame(t: float) -> Image.Image:
        canvas = Image.new("RGBA", (W, H))
        for p in parts:
            k = t - p["t0"]
            if k < 0:
                continue
            y = H + 60 - p["speed"] * k
            if y < -80:
                continue
            x = p["x"] + math.sin(p["wob"] + k * 3) * 30
            place(
                canvas,
                p["s"],
                x,
                y,
                alpha=min(1.0, k * 4) * min(1.0, y / 300 + 0.2),
                angle=math.sin(p["wob"] + k * 2) * 15,
            )
        return canvas

    return 3.0, frame


def speed_lines(_folder: Path) -> tuple[float, Callable[[float], Image.Image]]:
    rng = random.Random(13)
    rays = [
        dict(
            a=rng.uniform(0, 6.28),
            w=rng.uniform(3, 9),
            inner=rng.uniform(0.42, 0.62),
            on=rng.uniform(0, 1),
        )
        for _ in range(90)
    ]
    reach = math.hypot(W, H) / 2

    def frame(t: float) -> Image.Image:
        canvas = Image.new("RGBA", (W, H))
        draw = ImageDraw.Draw(canvas)
        step = int(t * 15)  # the lines flicker 15 times a second, like hand-drawn speed lines
        for i, r in enumerate(rays):
            if (step + i) % 3 == 0 and r["on"] < 0.5:
                continue
            a, inner = r["a"], r["inner"] * reach
            x0, y0 = W / 2 + math.cos(a) * inner, H / 2 + math.sin(a) * inner
            x1, y1 = W / 2 + math.cos(a) * reach, H / 2 + math.sin(a) * reach
            draw.line([(x0, y0), (x1, y1)], fill=(255, 255, 255, 230), width=int(r["w"]))
        return canvas

    return 1.0, frame


def magic_swirl(folder: Path) -> tuple[float, Callable[[float], Image.Image]]:
    twirls = [
        sprite(folder, f"twirl_0{i}", 520, c)
        for i, c in ((1, (170, 110, 255)), (2, (110, 200, 255)), (3, (255, 140, 230)))
    ]
    sparks = [sprite(folder, f"spark_0{i}", 90, (255, 240, 200)) for i in (1, 3, 5)]
    rng = random.Random(17)
    bits = [
        dict(
            a=rng.uniform(0, 6.28),
            r=rng.uniform(80, 260),
            s=rng.choice(sparks),
            sp=rng.uniform(2, 4),
        )
        for _ in range(18)
    ]

    def frame(t: float) -> Image.Image:
        canvas = Image.new("RGBA", (W, H))
        life = math.sin(math.pi * min(t / 2.0, 1.0))
        for i, tw in enumerate(twirls):
            place(
                canvas,
                tw,
                W / 2,
                H / 2,
                alpha=0.8 * life,
                angle=(200 + 60 * i) * t * (-1) ** i,
                scale=0.7 + 0.25 * i * life,
            )
        for b in bits:
            a = b["a"] + b["sp"] * t
            place(
                canvas,
                b["s"],
                W / 2 + math.cos(a) * b["r"],
                H / 2 + math.sin(a) * b["r"],
                alpha=life,
            )
        return canvas

    return 2.0, frame


def twinkles(folder: Path) -> tuple[float, Callable[[float], Image.Image]]:
    rng = random.Random(21)
    stars = [sprite(folder, f"star_0{i}", s, (255, 248, 210)) for i in (4, 6, 8) for s in (90, 130)]
    parts = [
        dict(
            x=rng.uniform(30, W - 30),
            y=rng.uniform(30, H - 30),
            s=rng.choice(stars),
            t0=rng.uniform(0, 3.0),
            d=rng.uniform(0.6, 1.0),
        )
        for _ in range(55)
    ]

    def frame(t: float) -> Image.Image:
        canvas = Image.new("RGBA", (W, H))
        for p in parts:
            k = ((t - p["t0"]) % 3.0) / p["d"]
            if k >= 1:
                continue
            place(
                canvas,
                p["s"],
                p["x"],
                p["y"],
                alpha=math.sin(math.pi * k),
                angle=90 * k,
                scale=0.6 + 0.6 * math.sin(math.pi * k),
            )
        return canvas

    return 3.0, frame


def explosion(folder: Path) -> tuple[float, Callable[[float], Image.Image]]:
    rng = random.Random(23)
    blasts = [sprite(folder, f"muzzle_0{i}", 420, (255, 170, 60)) for i in (1, 2, 4)]
    flames = [sprite(folder, f"flame_0{i}", 220, (255, 110, 20)) for i in (2, 5)]
    smoke = sprite(folder, "smoke_04", 520, (90, 85, 85))
    debris = [
        dict(
            a=rng.uniform(0, 6.28),
            d=rng.uniform(220, 520),
            s=rng.choice(flames),
            spin=rng.uniform(-300, 300),
        )
        for _ in range(18)
    ]

    def frame(t: float) -> Image.Image:
        canvas = Image.new("RGBA", (W, H))
        k = t / 1.4
        place(
            canvas,
            smoke,
            W / 2,
            H / 2 - 60 * k,
            alpha=0.75 * math.sin(math.pi * min(k * 1.1, 1)),
            scale=0.6 + 1.2 * ease_out(k),
        )
        for i, b in enumerate(blasts):
            place(
                canvas,
                b,
                W / 2,
                H / 2,
                alpha=max(0.0, 1 - k * 2.2),
                angle=40 * i + 90 * t,
                scale=0.4 + 1.6 * ease_out(k * 1.5),
            )
        for d in debris:
            r = ease_out(k) * d["d"]
            place(
                canvas,
                d["s"],
                W / 2 + math.cos(d["a"]) * r,
                H / 2 + math.sin(d["a"]) * r,
                alpha=max(0.0, 1 - k * 1.3),
                angle=d["spin"] * t,
                scale=0.7 - 0.4 * k,
            )
        return canvas

    return 1.4, frame


EFFECTS = {
    "confetti": ("Confetti", "celebrate", ["confetti", "party", "win"], confetti),
    "sparkle-burst": ("Sparkle burst", "celebrate", ["sparkle", "shine", "reveal"], sparkle_burst),
    "hearts": ("Rising hearts", "celebrate", ["hearts", "love", "cute"], hearts),
    "fire": ("Fire", "energy", ["fire", "hot", "flames"], fire),
    "explosion": ("Explosion", "energy", ["explosion", "boom", "blast"], explosion),
    "speed-lines": ("Speed lines", "energy", ["speed", "anime", "focus", "shock"], speed_lines),
    "flash": ("Flash", "transitions", ["flash", "white", "cut"], flash),
    "smoke-puff": ("Smoke puff", "transitions", ["smoke", "poof", "appear"], smoke_puff),
    "magic-swirl": ("Magic swirl", "magic", ["magic", "swirl", "transform"], magic_swirl),
    "twinkles": ("Twinkling stars", "magic", ["stars", "twinkle", "dreamy"], twinkles),
}


def render(name: str, folder: Path, out: Path) -> Path:
    seconds, frame = EFFECTS[name][3](folder)
    count = round(seconds * FPS)
    target = out / f"{name}.webm"
    with tempfile.TemporaryDirectory() as work:
        for i in range(count):
            frame(i / FPS).save(Path(work) / f"{i:04d}.png")
        subprocess.run(
            [
                FFMPEG,
                "-v",
                "error",
                "-y",
                "-framerate",
                str(FPS),
                "-i",
                f"{work}/%04d.png",
                "-c:v",
                "libvpx-vp9",
                "-pix_fmt",
                "yuva420p",
                "-b:v",
                "0",
                "-crf",
                "32",
                "-row-mt",
                "1",
                "-auto-alt-ref",
                "0",
                "-an",
                str(target),
            ],
            check=True,
            timeout=600,
        )
    return target


def main(folder: Path, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    listing = []
    for name, (title, category, tags, _make) in EFFECTS.items():
        path = render(name, folder, out)
        listing.append({"slug": name, "title": title, "category": category, "tags": tags})
        print(f"{path.name}: {path.stat().st_size} bytes")
    (out / "overlays.json").write_text(json.dumps({"items": listing}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2])))
