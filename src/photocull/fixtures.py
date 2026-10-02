"""Copyright-free deterministic fixtures for algorithm checks, not accuracy claims."""

import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

FIXTURE_VERSION = "synthetic_v1"


def generate_fixtures(folder: Path, count: int = 0):
    if count < 0 or count > 10000:
        raise ValueError("Fixture count must be within 0..10000")
    folder.mkdir(parents=True, exist_ok=True)
    if any(folder.iterdir()):
        raise ValueError("Fixture destination must be empty; existing files are never overwritten")
    y, x = np.indices((256, 256))
    board = ((x // 16 + y // 16) % 2 * 255).astype(np.uint8)
    sharp = Image.fromarray(board).convert("RGB")
    sharp.save(folder / "sharp.png")
    sharp.filter(ImageFilter.GaussianBlur(4)).save(folder / "blurred.png")
    for name, value in (("dark", 4), ("bright", 251), ("normal", 128)):
        Image.new("RGB", (256, 256), (value, value, value)).save(folder / f"{name}.png")
    Image.fromarray((120 + (board > 0) * 16).astype(np.uint8)).save(folder / "low_contrast.png")
    sharp.save(folder / "high_contrast.png")
    rng = np.random.default_rng(1704)
    noise = np.clip(128 + rng.normal(0, 25, (256, 256, 3)), 0, 255).astype(np.uint8)
    Image.fromarray(noise).save(folder / "noisy.png")
    sharp.resize((128, 128), Image.Resampling.LANCZOS).save(folder / "resized.png")
    sharp.crop((16, 16, 240, 240)).save(folder / "cropped.png")
    sharp.save(folder / "reencoded.jpg", quality=90)
    sharp.save(folder / "webp.webp", lossless=True)
    shutil.copyfile(folder / "sharp.png", folder / "exact.png")
    (folder / "corrupt.jpg").write_bytes(b"not an image")
    (folder / "unsupported.txt").write_text("Local generated fixture\n")
    orientation = Image.Exif()
    orientation[274] = 6
    oriented = Image.new("RGB", (80, 40), "red")
    oriented.save(folder / "orientation.jpg", exif=orientation)
    for i in range(3):
        exif = Image.Exif()
        exif[34665] = {36867: f"2026:01:01 12:00:0{i}", 36881: "-06:00"}
        sharp.save(folder / f"burst_{i}.jpg", exif=exif)
    for i in range(count):
        variation = np.clip(noise.astype(np.int16) + (i % 31) - 15, 0, 255).astype(np.uint8)
        Image.fromarray(variation).save(folder / f"extra_{i:05d}.png")
    return {
        "fixture_version": FIXTURE_VERSION,
        "seed": 1704,
        "image_files": 18 + count,
        "extra_images": count,
    }
