"""Deterministic public-safe illustrated landscapes. No third-party or personal photos."""

import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent / "assets/demo"


def scene(seed):
    rng = np.random.default_rng(seed)
    w, h = 640, 400
    yy, xx = np.indices((h, w))
    sky = np.stack([46 + yy * 0.14, 118 + yy * 0.12, 150 + yy * 0.09], axis=-1)
    sky = np.clip(sky + rng.normal(0, 1.5, (h, w, 1)), 0, 255).astype(np.uint8)
    image = Image.fromarray(sky)
    draw = ImageDraw.Draw(image)
    draw.ellipse((420, 35, 480, 95), fill="#ffe3a7")
    draw.polygon(
        [
            (0, 245),
            (105, 112),
            (225, 245),
            (335, 100),
            (520, 250),
            (640, 155),
            (640, 400),
            (0, 400),
        ],
        fill="#457c78",
    )
    draw.polygon(
        [(0, 270), (160, 185), (320, 265), (480, 165), (640, 280), (640, 400), (0, 400)],
        fill="#2e6462",
    )
    draw.rectangle((0, 278, w, h), fill="#7cadb5")
    for _i in range(60):
        x = int(rng.integers(w))
        y = int(rng.integers(290, h))
        draw.line((x, y, min(x + int(rng.integers(15, 85)), w), y), fill="#a5cbd0", width=1)
    draw.polygon([(0, 370), (190, 280), (210, 400), (0, 400)], fill="#295454")
    for i in range(10):
        x = 15 + i * 18
        y = 320 - int(rng.integers(20))
        draw.rectangle((x, y, x + 3, y + 38), fill="#264b42")
        draw.polygon([(x - 12, y + 12), (x + 1, y - 24), (x + 14, y + 12)], fill="#47784f")
        draw.polygon([(x - 10, y), (x + 1, y - 31), (x + 12, y)], fill="#5b895c")
    draw.polygon([(330, 322), (400, 322), (385, 335), (345, 335)], fill="#e7b891")
    draw.line((368, 288, 368, 322), fill="#f8edd8", width=2)
    draw.polygon([(366, 290), (341, 317), (366, 317)], fill="#f5dfb5")
    for _i in range(9):
        x = int(rng.integers(w))
        y = int(rng.integers(100, 200))
        draw.arc((x, y, x + 15, y + 7), 180, 350, fill="#d5e5e3", width=2)
    return image


def save(image, name, time):
    exif = Image.Exif()
    exif[34665] = {36867: time, 36881: "+00:00"}
    with io.BytesIO() as stream:
        image.save(stream, "JPEG", quality=90, exif=exif)
        (ROOT / name).write_bytes(stream.getvalue())


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    base = scene(170407)
    save(base, "01-lakeside.jpg", "2026:01:01 10:00:00")
    (ROOT / "02-lakeside-copy.jpg").write_bytes((ROOT / "01-lakeside.jpg").read_bytes())
    save(base, "03-lakeside-reencoded.jpg", "2026:01:01 10:00:01")
    # Distinct small camera pans form a burst; no copy/delete recommendations for bursts.
    for i in range(3):
        pan = base.crop((i * 18, 0, 640 - (2 - i) * 18, 400)).resize(
            (640, 400), Image.Resampling.LANCZOS
        )
        save(pan, f"0{4 + i}-camera-pan.jpg", f"2026:01:01 10:05:0{i}")
    warm = scene(170408)
    pixels = np.asarray(warm).copy()
    pixels[:, :, 0] = np.clip(pixels[:, :, 0].astype(float) * 1.25, 0, 255).astype(np.uint8)
    warm = Image.fromarray(pixels)
    save(warm, "07-golden-hour.jpg", "2026:01:01 16:30:00")
    save(warm.filter(ImageFilter.GaussianBlur(3)), "08-soft-focus.jpg", "2026:01:01 16:30:01")
    dark = Image.fromarray((np.asarray(warm).astype(float) * 0.22).astype(np.uint8))
    save(dark, "09-low-light.jpg", "2026:01:01 16:31:00")
    for i in range(3):
        different = scene(170420 + i)
        draw = ImageDraw.Draw(different)
        draw.rectangle(
            (180 + i * 60, 210, 230 + i * 60, 280), fill=("#bd9a75", "#d8b98d", "#8ca588")[i]
        )
        draw.polygon(
            [(170 + i * 60, 210), (205 + i * 60, 175), (240 + i * 60, 210)], fill="#76584c"
        )
        save(different, f"{10 + i}-weekend-trip.jpg", f"2026:01:03 12:{i * 20:02d}:00")
    (ROOT / "manifest.json").write_text(
        json.dumps(
            {
                "version": "public_demo_v1",
                "license": "CC0-1.0",
                "source": "PhotoCull deterministic generated illustrations, no real photos",
                "seed": 170407,
                "files": sorted(p.name for p in ROOT.glob("*.jpg")),
            },
            indent=2,
        )
        + "\n"
    )
    (ROOT / "LICENSE.txt").write_text(
        "PhotoCull generated demo illustrations are dedicated to the public domain under CC0 1.0.\n"
        "No personal or third-party photographs are included.\n"
        "https://creativecommons.org/publicdomain/zero/1.0/\n"
    )


if __name__ == "__main__":
    main()
