"""Versioned private/synthetic manifests, development-only tuning and held-out evaluation."""

import csv
import io
import json
import tempfile
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from photocull import __version__
from photocull.config import DuplicateConfig, QualityConfig, parameter_hash
from photocull.hashing import PerceptualHashService
from photocull.quality import QualityAnalyzer
from photocull.scanner import PhotoScanner
from photocull.similarity import PhotoFeatures, SimilarityEngine, pair_key, verification_from_image

DATASET_VERSION = "synthetic_duplicates_v1"
LABELS = {
    "EXACT_DUPLICATE",
    "NEAR_DUPLICATE",
    "BURST_SAME_MOMENT",
    "SIMILAR_BUT_NOT_DUPLICATE",
    "UNRELATED",
}


def scene(seed, size=256):
    """Randomized textured geometric scenes; disjoint seed families across splits."""
    rng = np.random.default_rng(seed)
    y, x = np.indices((size, size))
    base = np.stack((50 + x * 0.45, 50 + y * 0.45, 45 + (x + y) * 0.25), axis=2)
    base += rng.normal(0, 3, base.shape)
    image = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(image)
    for _ in range(24):
        x0, y0 = rng.integers(0, size - 50, 2)
        w, h = rng.integers(15, 65, 2)
        color = tuple(int(v) for v in rng.integers(20, 235, 3))
        draw.rectangle((int(x0), int(y0), int(x0 + w), int(y0 + h)), fill=color)
    return image


def generate_duplicate_dataset(folder: Path, families=12):
    folder.mkdir(parents=True, exist_ok=True)
    if any(folder.iterdir()):
        raise ValueError("Duplicate fixture destination must be empty")
    image_dir = folder / "photos"
    image_dir.mkdir()
    photos, pairs = [], []

    def add(identifier, image, split, family, **metadata):
        path = image_dir / f"{identifier}.png"
        if metadata.get("capture_time"):
            exif = Image.Exif()
            value = metadata["capture_time"].replace("-", ":").replace("T", " ")
            exif[34665] = {36867: value, 36881: metadata.get("capture_timezone", "+00:00")}
            image.save(path, exif=exif)
        else:
            image.save(path)
        photos.append(
            {
                "id": identifier,
                "path": str(path.relative_to(folder)),
                "split": split,
                "family": family,
                **metadata,
            }
        )
        return identifier

    for split, seed_base in (("development", 1704), ("held_out", 81704)):
        for index in range(families):
            family = f"{split}-{index:02d}"
            base = scene(seed_base + index)
            original = add(f"{family}-base", base, split, family)
            transformations = {
                "exact": (base, "EXACT_DUPLICATE"),
                "resize": (base.resize((384, 384)), "NEAR_DUPLICATE"),
                "slight_crop": (base.crop((3, 3, 253, 253)), "NEAR_DUPLICATE"),
                "moderate_crop": (base.crop((64, 64, 192, 192)), "SIMILAR_BUT_NOT_DUPLICATE"),
                "brightness": (ImageEnhance.Brightness(base).enhance(1.12), "NEAR_DUPLICATE"),
                "contrast": (ImageEnhance.Contrast(base).enhance(0.85), "NEAR_DUPLICATE"),
                "rotation": (base.rotate(2, resample=Image.Resampling.BICUBIC), "NEAR_DUPLICATE"),
                "blur": (base.filter(ImageFilter.GaussianBlur(1.5)), "NEAR_DUPLICATE"),
                "unrelated": (scene(seed_base + 1000 + index), "UNRELATED"),
            }
            for name, (image, label) in transformations.items():
                identifier = add(f"{family}-{name}", image, split, family)
                pairs.append({"a": original, "b": identifier, "label": label, "split": split})
            jpeg_id = f"{family}-recompressed"
            jpeg_path = image_dir / f"{jpeg_id}.jpg"
            base.save(jpeg_path, quality=55)
            photos.append(
                {
                    "id": jpeg_id,
                    "path": str(jpeg_path.relative_to(folder)),
                    "split": split,
                    "family": family,
                }
            )
            pairs.append({"a": original, "b": jpeg_id, "label": "NEAR_DUPLICATE", "split": split})
            # Distinct nearby captures: a visible moving shape on a shared textured background.
            burst_ids = []
            for frame, seconds in enumerate((0, 3, 7)):
                moment = base.copy()
                draw = ImageDraw.Draw(moment)
                start = 65 + frame * 25
                draw.rectangle((start, 80, start + 35, 125), fill=(245, 20, 20))
                identifier = add(
                    f"{family}-burst{frame}",
                    moment,
                    split,
                    family,
                    capture_time=f"2026-01-{index + 1:02d}T12:00:{seconds:02d}",
                    capture_timezone="+00:00",
                )
                burst_ids.append(identifier)
            for a, b in ((burst_ids[0], burst_ids[1]), (burst_ids[1], burst_ids[2])):
                pairs.append({"a": a, "b": b, "label": "BURST_SAME_MOMENT", "split": split})
            # Same-looking captures months apart: deliberately negative for near and burst.
            far = add(
                f"{family}-far",
                base.filter(ImageFilter.GaussianBlur(0.5)),
                split,
                family,
                capture_time="2026-07-01T12:00:00",
                capture_timezone="+00:00",
            )
            dated = add(
                f"{family}-dated",
                base,
                split,
                family,
                capture_time="2026-01-01T12:00:00",
                capture_timezone="+00:00",
            )
            pairs.append(
                {"a": dated, "b": far, "label": "SIMILAR_BUT_NOT_DUPLICATE", "split": split}
            )
        # Adversarial cases are independently generated for each split.
        for category in ("sunset", "wall", "screenshot", "dark", "sky", "document", "pattern"):
            ids = []
            for variant in (0, 1):
                image = Image.new(
                    "RGB", (256, 256), (10, 10, 10) if category == "dark" else (175, 180, 190)
                )
                draw = ImageDraw.Draw(image)
                offset = 12 if split == "held_out" else 0
                if category in {"sky", "sunset"}:
                    for y in range(256):
                        color = (
                            (230 - y // 3, 90 + y // 3, 55 + variant * 15)
                            if category == "sunset"
                            else (90 + variant * 8, 130 + y // 3, 220)
                        )
                        draw.line((0, y, 255, y), fill=color)
                    draw.ellipse(
                        (20 + variant * 130, 30 + offset, 65 + variant * 130, 75 + offset),
                        fill=(220, 210, 185),
                    )
                elif category in {"document", "screenshot"}:
                    draw.rectangle((12, 10, 244, 245), fill="white")
                    for y in range(30, 230, 16):
                        draw.line((25, y, 220 - variant * 40, y), fill="black", width=2)
                    draw.rectangle(
                        (30 + variant * 80, 60 + offset, 70 + variant * 80, 100 + offset),
                        fill=(30, 120, 190),
                    )
                elif category == "pattern":
                    for x in range(0, 256, 16):
                        draw.rectangle(
                            (x + offset, variant * 7, x + offset + 7, 255), fill=(70, 80, 95)
                        )
                else:
                    draw.rectangle(
                        (40 + variant * 110, 40 + offset, 55 + variant * 110, 55 + offset),
                        fill=(17, 17, 17) if category == "dark" else (166, 169, 179),
                    )
                identifier = add(
                    f"{split}-negative-{category}-{variant}",
                    image,
                    split,
                    f"{split}-negative-{category}",
                )
                ids.append(identifier)
            pairs.append(
                {
                    "a": ids[0],
                    "b": ids[1],
                    "label": "SIMILAR_BUT_NOT_DUPLICATE",
                    "split": split,
                    "category": category,
                }
            )
    manifest = {
        "dataset_version": DATASET_VERSION,
        "seed": [1704, 81704],
        "photos": photos,
        "pairs": pairs,
        "limitations": "Geometric synthetic scenes; no real-photo accuracy claim.",
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def load_manifest(path: Path):
    manifest = json.loads(path.read_text())
    if not manifest.get("dataset_version"):
        raise ValueError("Manifest needs dataset_version")
    photos, seen = [], set()
    content_splits = {}
    scanner, quality, hashes = (
        PhotoScanner(),
        QualityAnalyzer(QualityConfig()),
        PerceptualHashService(),
    )
    split_by_id, family_splits = {}, {}
    for record in manifest["photos"]:
        if record["id"] in seen:
            raise ValueError("Manifest contains duplicate IDs")
        seen.add(record["id"])
        if record["split"] not in {"development", "held_out"}:
            raise ValueError("Use development or held_out split")
        family = record["family"]
        if family in family_splits and family_splits[family] != record["split"]:
            raise ValueError("Family leakage across development/held-out splits")
        family_splits[family] = record["split"]
        split_by_id[record["id"]] = record["split"]
        image, meta = scanner.read((path.parent / record["path"]).resolve(), 80_000_000)
        digest = meta["content_sha256"]
        if digest in content_splits and content_splits[digest] != record["split"]:
            raise ValueError("Byte-identical photo leakage across development/held-out splits")
        content_splits[digest] = record["split"]
        # Use the same lossy local-preview preprocessing as production detection.
        preview = image.copy()
        preview.thumbnail((512, 512), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        preview.save(buffer, format="JPEG", quality=85)
        buffer.seek(0)
        with Image.open(buffer) as thumb:
            verification = verification_from_image(thumb)
        photos.append(
            (
                record["split"],
                PhotoFeatures(
                    id=record["id"],
                    fingerprint=meta["fingerprint"],
                    sha256=meta["content_sha256"],
                    width=image.width,
                    height=image.height,
                    size=meta["file_size"],
                    hashes=hashes.analyze(image),
                    quality=quality.analyze(image),
                    capture_time=record.get("capture_time", meta["capture_time"]),
                    capture_timezone=record.get("capture_timezone", meta["capture_timezone"]),
                    # Do not infer capture times from fixture creation times.
                    filesystem_time=record.get("filesystem_time"),
                    filename=record["id"] + ".png",
                    verification=verification,
                ),
            )
        )
        image.close()
    expanded = list(manifest.get("pairs", []))
    for group in manifest.get("groups", []):
        members = group["members"]
        if len(members) > 256 or len(set(members)) != len(members):
            raise ValueError("Evaluation groups need unique IDs and at most 256 members")
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                expanded.append({"a": a, "b": b, "split": group["split"], "label": group["label"]})
    seen_pairs = {}
    for pair in expanded:
        if pair["label"] not in LABELS or pair["a"] == pair["b"]:
            raise ValueError("Invalid pair label or self-pair")
        if (
            split_by_id.get(pair["a"]) != pair["split"]
            or split_by_id.get(pair["b"]) != pair["split"]
        ):
            raise ValueError("Pair crosses splits or references an unknown photo")
        key = (pair["split"], pair_key(pair["a"], pair["b"]))
        if key in seen_pairs and seen_pairs[key]["label"] != pair["label"]:
            raise ValueError("Conflicting labels for a pair")
        seen_pairs[key] = pair
    manifest["pairs"] = list(seen_pairs.values())
    if not any(s == "development" for s, _ in photos) or not any(
        s == "held_out" for s, _ in photos
    ):
        raise ValueError("Both development and held_out photos are required")
    return manifest, photos


def binary_metrics(truth, predicted):
    tp = sum(t and p for t, p in zip(truth, predicted, strict=True))
    fp = sum(not t and p for t, p in zip(truth, predicted, strict=True))
    fn = sum(t and not p for t, p in zip(truth, predicted, strict=True))
    tn = sum(not t and not p for t, p in zip(truth, predicted, strict=True))
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
        "false_positive_rate": fp / (fp + tn) if fp + tn else None,
    }


def score_split(engine, photos, labels):
    by_id = {p.id: p for p in photos}
    result = engine.detect(photos)
    grouped = {name: set() for name in ("EXACT_DUPLICATE", "NEAR_DUPLICATE", "BURST_GROUP")}
    for group in result["groups"]:
        members = group["members"]
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                grouped[group["type"]].add(pair_key(a, b))
    measurements = []
    for label in labels:
        value = engine.compare(by_id[label["a"]], by_id[label["b"]])
        measurements.append(
            {
                **label,
                **value,
                "grouped_exact": pair_key(label["a"], label["b"]) in grouped["EXACT_DUPLICATE"],
                "grouped_near": pair_key(label["a"], label["b"]) in grouped["NEAR_DUPLICATE"],
                "grouped_burst": pair_key(label["a"], label["b"]) in grouped["BURST_GROUP"],
            }
        )
    metrics = {}
    # Near classifier metric excludes exact labels, which have a separate deterministic detector.
    for name, label_name, field in (
        ("exact", "EXACT_DUPLICATE", "grouped_exact"),
        ("near", "NEAR_DUPLICATE", "near"),
        ("burst", "BURST_SAME_MOMENT", "burst"),
        ("near_grouped", "NEAR_DUPLICATE", "grouped_near"),
        ("burst_grouped", "BURST_SAME_MOMENT", "grouped_burst"),
    ):
        rows = [r for r in measurements if name == "exact" or r["label"] != "EXACT_DUPLICATE"]
        metrics[name] = binary_metrics(
            [r["label"] == label_name for r in rows], [bool(r[field]) for r in rows]
        )
    return {"metrics": metrics, "measurements": measurements, "statistics": result["statistics"]}


def evaluate_duplicates(manifest_path: Path | None = None, config=None):
    config = config or DuplicateConfig()
    if manifest_path is None:
        with tempfile.TemporaryDirectory(prefix="photocull-evaluation-") as temporary:
            root = Path(temporary).resolve()
            generate_duplicate_dataset(root)
            return evaluate_duplicates(root / "manifest.json", config)
    manifest, records = load_manifest(manifest_path)
    splits = {name: [p for s, p in records if s == name] for name in ("development", "held_out")}
    labels = {name: [p for p in manifest["pairs"] if p["split"] == name] for name in splits}
    experiments = []
    verification_experiment = []
    for correlation in (0.95, 0.98, 0.99, 0.995, 0.999):
        variant = replace(config, phash_distance=6, verification_correlation=correlation)
        scored = score_split(
            SimilarityEngine(variant), splits["development"], labels["development"]
        )
        verification_experiment.append({"correlation": correlation, **scored["metrics"]["near"]})
    for threshold in (0, 2, 4, 6, 8, 10, 12):
        variant = replace(config, phash_distance=threshold)
        scored = score_split(
            SimilarityEngine(variant), splits["development"], labels["development"]
        )
        experiments.append(
            {
                "phash_threshold": threshold,
                **scored["metrics"]["near"],
                "group_metrics": scored["metrics"]["near_grouped"],
            }
        )
    # Require observed precision >=98%, some true positives; maximize recall, then prefer smaller p.
    eligible = [e for e in experiments if e["tp"] > 0 and e["precision"] >= 0.98]
    if not eligible:
        raise ValueError("No tested pHash threshold met the development precision target")
    chosen = max(eligible, key=lambda e: (e["recall"], -e["phash_threshold"]))
    selected = replace(config, phash_distance=chosen["phash_threshold"])
    burst_experiments = []
    for window in (2.0, 5.0, 10.0):
        score = score_split(
            SimilarityEngine(replace(selected, burst_window=window)),
            splits["development"],
            labels["development"],
        )
        burst_experiments.append({"window_seconds": window, **score["metrics"]["burst"]})
    viable = [e for e in burst_experiments if e["tp"] > 0 and e["precision"] >= 0.98]
    if viable:
        window = max(viable, key=lambda e: (e["recall"], -e["window_seconds"]))["window_seconds"]
        selected = replace(selected, burst_window=window)
    development = score_split(
        SimilarityEngine(selected), splits["development"], labels["development"]
    )
    held_out = score_split(SimilarityEngine(selected), splits["held_out"], labels["held_out"])
    composition = {
        split: {
            "photos": len(splits[split]),
            "labeled_pairs": len(labels[split]),
            "labels": {
                name: sum(p["label"] == name for p in labels[split]) for name in sorted(LABELS)
            },
        }
        for split in splits
    }
    false_positives = []
    hard_negatives = []
    for split, scored in (("development", development), ("held_out", held_out)):
        for row in scored["measurements"]:
            if row["label"] in {"SIMILAR_BUT_NOT_DUPLICATE", "UNRELATED"}:
                hard_negatives.append({"split": split, **row})
            if row["near"] and row["label"] not in {"NEAR_DUPLICATE", "EXACT_DUPLICATE"}:
                false_positives.append({"split": split, **row})
    return {
        "app_version": __version__,
        "dataset_version": manifest["dataset_version"],
        "manifest_label_hash": parameter_hash({"pairs": manifest["pairs"]}),
        "dataset_content_hash": parameter_hash({p.id: p.sha256 for _, p in records}),
        "quality_parameters": QualityAnalyzer(QualityConfig()).parameters,
        "hash_parameters": PerceptualHashService.parameters,
        "verification_experiment": verification_experiment,
        "selection": "Development only; observed precision >=0.98, maximize recall, smaller tie",
        "selected_config": asdict(selected),
        "algorithm_version": SimilarityEngine.version,
        "analysis_parameters": SimilarityEngine(selected).parameters,
        "composition": composition,
        "threshold_experiment": experiments,
        "burst_experiment": burst_experiments,
        "development": development,
        "held_out": held_out,
        "false_positives": false_positives,
        "hard_negative_analysis": hard_negatives,
        "limitations": "Synthetic benchmark unless a private manifest is supplied. "
        "No deletion actions. False recommendations carry greater risk than missed matches.",
    }


def evaluation_csv(report):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "split",
            "a",
            "b",
            "label",
            "prediction",
            "phash",
            "dhash",
            "ahash",
            "correlation",
            "grouped_near",
            "grouped_burst",
        ]
    )
    for split in ("development", "held_out"):
        for row in report[split]["measurements"]:
            e = row["evidence"]
            writer.writerow(
                [
                    split,
                    row["a"],
                    row["b"],
                    row["label"],
                    row["relationship"],
                    e["phash"],
                    e["dhash"],
                    e["ahash"],
                    e["verification_correlation"],
                    row["grouped_near"],
                    row["grouped_burst"],
                ]
            )
    return output.getvalue()
