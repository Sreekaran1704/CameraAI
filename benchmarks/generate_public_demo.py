"""Package generated photographic renders with deterministic demo identities/timestamps.

Image content/quality/burst edits were created by the built-in image generator. This
script only encodes, resizes duplicate examples, copies files and adds fixture EXIF.
"""

import hashlib
import io
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent / "assets/demo"
SAMPLES = [
    ("01-lake-original.jpg", "lake", "Original landscape", "Original", "Lake morning", 0, None, 92),
    ("02-lake-exact-copy.jpg", None, "Exact copy", "Exact copy", "Lake morning", 0, None, 92),
    (
        "03-lake-recompressed.jpg",
        "lake",
        "Same view, compressed",
        "Recompressed",
        "Lake morning",
        20,
        None,
        70,
    ),
    (
        "04-lake-resized.jpg",
        "lake",
        "Same view, smaller file",
        "Resized",
        "Lake morning",
        40,
        768,
        92,
    ),
    ("05-cafe-sharp.jpg", "cafe", "Sharp original", "Sharp", "Cafe afternoon", 0, None, 92),
    (
        "06-cafe-blurred.jpg",
        "cafe-blurred",
        "Missed focus",
        "Blurred",
        "Cafe afternoon",
        20,
        None,
        92,
    ),
    ("07-cafe-dark.jpg", "cafe-dark", "Too dark", "Underexposed", "Cafe afternoon", 40, None, 92),
    (
        "08-cafe-bright.jpg",
        "cafe-bright",
        "Too bright",
        "Overexposed",
        "Cafe afternoon",
        60,
        None,
        92,
    ),
    (
        "09-cafe-resized.jpg",
        "cafe",
        "Sharp, smaller file",
        "Resized",
        "Cafe afternoon",
        80,
        768,
        92,
    ),
    ("10-dog-burst-1.jpg", "dog-1", "Burst frame 1", "Burst frame", "Park run", 0, None, 92),
    ("11-dog-burst-2.jpg", "dog-2", "Burst frame 2", "Burst frame", "Park run", 2, None, 92),
    ("12-dog-burst-3.jpg", "dog-3", "Burst frame 3", "Burst frame", "Park run", 4, None, 92),
]
NOTES = {
    "Lake morning": (
        "Compare the red canoe, dock and mountains. Exact copies look identical; "
        "compressed/resized files can too."
    ),
    "Cafe afternoon": (
        "Compare latte-art edges, croissant flakes and wood grain. "
        "Blur removes detail; exposure hides or clips it."
    ),
    "Park run": (
        "Compare the dog's paws and stride. These synthetic frames depict "
        "a changing moment, not identical copies."
    ),
}


def main():
    from datetime import datetime, timedelta

    ROOT.mkdir(parents=True, exist_ok=True)
    previous = (
        json.loads((ROOT / "manifest.json").read_text())
        if (ROOT / "manifest.json").exists()
        else {}
    )
    samples = []
    bases = {
        "Lake morning": datetime(2026, 1, 1, 9),
        "Cafe afternoon": datetime(2026, 1, 1, 14),
        "Park run": datetime(2026, 1, 3, 11),
    }
    for filename, source, label, kind, occasion, seconds, edge, quality in SAMPLES:
        target = ROOT / filename
        if source is None:
            target.write_bytes((ROOT / "01-lake-original.jpg").read_bytes())
        else:
            exif = Image.Exif()
            timestamp = bases[occasion] + timedelta(seconds=seconds)
            exif[34665] = {36867: timestamp.strftime("%Y:%m:%d %H:%M:%S"), 36881: "+00:00"}
            with Image.open(ROOT / "sources" / f"{source}.jpg") as image:
                if edge:
                    image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
                with io.BytesIO() as stream:
                    image.save(stream, "JPEG", quality=quality, exif=exif)
                    target.write_bytes(stream.getvalue())
        samples.append(
            {
                "file": filename,
                "label": label,
                "intended_example": kind,
                "occasion": occasion,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        )
    files = [s["file"] for s in samples]
    manifest = {
        "version": "public_demo_v2",
        "license": "CC0-1.0",
        "source": "AI-generated photographic renders and edits; no personal photographs",
        "timestamps": "Authored teaching-fixture EXIF, not authentic camera capture evidence",
        "files": files,
        "samples": samples,
        "comparisons": [
            {
                "name": "Spot the quality differences",
                "note": NOTES["Cafe afternoon"],
                "files": files[4:8],
                "reference": files[4],
            },
            {
                "name": "Identical-looking photos, different files",
                "note": NOTES["Lake morning"],
                "files": files[:4],
                "reference": files[0],
            },
            {
                "name": "A burst is a changing moment",
                "note": NOTES["Park run"],
                "files": files[9:],
                "reference": files[9],
            },
        ],
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    # Remove only former manifest-owned JPEG assets explicitly replaced by this dataset.
    for filename in previous.get("files", []):
        if filename not in files and Path(filename).name == filename:
            (ROOT / filename).unlink(missing_ok=True)
    (ROOT / "LICENSE.txt").write_text(
        "PhotoCull synthetic photographic demo renders/edits are dedicated under CC0 1.0.\n"
        "Created with the built-in OpenAI image generator; no personal or third-party photos.\n"
        "Scenes and timestamps are synthetic teaching examples, not recorded real occasions.\n"
        "https://creativecommons.org/publicdomain/zero/1.0/\n"
    )


if __name__ == "__main__":
    main()
