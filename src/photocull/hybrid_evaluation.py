"""Frozen Phase 2 A/B experiment with development-only operating-point selection."""

import json
import time
from dataclasses import asdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from photocull.cache import Cache
from photocull.config import DuplicateConfig, EmbeddingConfig, parameter_hash
from photocull.duplicate_evaluation import load_manifest, score_split
from photocull.embeddings import MODELS, EmbeddingService
from photocull.hybrid import HybridEngine
from photocull.similarity import SimilarityEngine


def expand_hard_dataset(frozen_manifest, destination):
    """Preserve original labels; add separate hard families with unambiguous synthetic content."""
    manifest = json.loads(frozen_manifest.read_text())
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError("Hard fixture destination must be empty")
    for photo in manifest["photos"]:
        photo["path"] = str((frozen_manifest.parent / photo["path"]).resolve())
    original = list(manifest["photos"])
    for photo in original:
        if not photo["id"].endswith("-base"):
            continue
        base = Image.open(photo["path"]).convert("RGB")
        transforms = {
            "crop6": base.crop((6, 6, 250, 250)).resize((256, 256)),
            "rotation3": base.rotate(3, resample=Image.Resampling.BICUBIC),
            "perspective": base.transform(
                (256, 256),
                Image.Transform.PERSPECTIVE,
                (1, 0.015, -2, -0.01, 1, 2, 0.00004, -0.00004),
                Image.Resampling.BICUBIC,
            ),
            "grade": ImageEnhance.Color(base).enhance(0.80),
            "contrast_hard": ImageEnhance.Contrast(base).enhance(1.20),
            "brightness_hard": ImageEnhance.Brightness(base).enhance(0.80),
            "blur_hard": base.filter(ImageFilter.GaussianBlur(2)),
        }
        obstruction = base.copy()
        ImageDraw.Draw(obstruction).rectangle((115, 110, 131, 126), fill=(80, 80, 80))
        transforms["obstruction"] = obstruction
        # Distinct content variants retain broadly similar layout/tone.
        product = base.copy()
        ImageDraw.Draw(product).rectangle((40, 70, 85, 120), fill=(220, 180, 20))
        transforms["product_negative"] = product
        for name, image in transforms.items():
            identifier = f"{photo['id']}-{name}"
            path = destination / f"{identifier}.png"
            image.save(path)
            manifest["photos"].append({**photo, "id": identifier, "path": str(path.resolve())})
            manifest["pairs"].append(
                {
                    "a": photo["id"],
                    "b": identifier,
                    "label": "SIMILAR_BUT_NOT_DUPLICATE"
                    if name.endswith("negative")
                    else "NEAR_DUPLICATE",
                    "split": photo["split"],
                    "category": name,
                }
            )
    manifest["dataset_version"] = "phase3_hard_v1"
    result = destination / "manifest.json"
    result.write_text(json.dumps(manifest, indent=2))
    return result


def records_for_manifest(manifest_path, manifest, features):
    by_id = {p.id: p for _, p in features}
    records = []
    for row in manifest["photos"]:
        path = (manifest_path.parent / row["path"]).resolve()

        def loader(path=path):
            with Image.open(path) as image:
                return image.copy()

        records.append((row["id"], by_id[row["id"]].fingerprint, loader))
    return records


def metrics_row(scored):
    m = dict(scored["metrics"]["near"])
    m["false_negative_rate"] = m["fn"] / (m["tp"] + m["fn"]) if m["tp"] + m["fn"] else None
    return m


def compare_changes(base, scored):
    lookup = {(r["a"], r["b"]): r for r in base["measurements"]}
    recovered, false_positives, unchanged = [], [], 0
    for row in scored["measurements"]:
        before = lookup[row["a"], row["b"]]
        if row["label"] == "EXACT_DUPLICATE":
            continue
        if row["near"] and not before["near"]:
            if row["label"] == "NEAR_DUPLICATE":
                recovered.append(row)
            else:
                false_positives.append(row)
        if bool(row["near"]) == bool(before["near"]):
            unchanged += 1
    return {
        "recovered_true_positives": len(recovered),
        "new_false_positives": len(false_positives),
        "unchanged_cases": unchanged,
        "recovered_examples": recovered,
        "new_false_positive_examples": false_positives,
    }


def evaluate_hybrid(manifest_path, cache_dir, hard_manifest=None):
    started = time.perf_counter()
    manifest, features = load_manifest(manifest_path)
    splits = {s: [p for split, p in features if split == s] for s in ("development", "held_out")}
    labels = {s: [r for r in manifest["pairs"] if r["split"] == s] for s in splits}
    frozen = DuplicateConfig()
    base = {s: score_split(SimilarityEngine(frozen), splits[s], labels[s]) for s in splits}
    report = {
        "dataset_version": manifest["dataset_version"],
        "label_hash": parameter_hash({"pairs": manifest["pairs"]}),
        "content_hash": parameter_hash({p.id: p.sha256 for _, p in features}),
        "frozen_hash_config": asdict(frozen),
        "baseline_algorithm_version": SimilarityEngine.version,
        "baseline": base,
        "models": {},
    }
    cache = Cache(cache_dir)
    for model in MODELS:
        service = EmbeddingService(cache, model)
        vectors, timings = service.encode(records_for_manifest(manifest_path, manifest, features))
        experiments = []
        # Prespecified search, only development labels select thresholds.
        for threshold in (0.95, 0.97, 0.98, 0.99, 0.995, 0.999):
            for pixel_floor in (0.90, 0.95, 0.98):
                for radius in (8, 12, 16):
                    config = EmbeddingConfig(
                        model=model,
                        cosine_threshold=threshold,
                        pixel_floor=pixel_floor,
                        moderate_phash=radius,
                    )
                    engine = HybridEngine(frozen, config, vectors, service.identity)
                    scored = score_split(engine, splits["development"], labels["development"])
                    experiments.append({"config": asdict(config), **metrics_row(scored)})
        eligible = [e for e in experiments if e["precision"] is not None and e["precision"] >= 0.98]
        if not eligible:
            fallback = EmbeddingConfig(model=model, recovery_enabled=False)
            eligible = [{"config": asdict(fallback), **metrics_row(base["development"])}]
        chosen = max(
            eligible,
            key=lambda e: (
                e["recall"],
                e["precision"],
                e["config"]["cosine_threshold"],
                e["config"]["pixel_floor"],
                -e["config"]["moderate_phash"],
            ),
        )
        selected = EmbeddingConfig(**chosen["config"])
        scored = {
            s: score_split(
                HybridEngine(frozen, selected, vectors, service.identity), splits[s], labels[s]
            )
            for s in splits
        }
        held = metrics_row(scored["held_out"])
        result = {
            "spec": asdict(service.spec),
            "algorithm_version": HybridEngine.version,
            "analysis_parameters": HybridEngine(
                frozen, selected, vectors, service.identity
            ).parameters,
            "identity": service.identity,
            "weight_bytes": service.path.stat().st_size,
            "timings": timings,
            "threshold_experiment": experiments,
            "selected_config": asdict(selected),
            "development": metrics_row(scored["development"]),
            "held_out": held,
            "grouped_metrics": scored["held_out"]["metrics"]["near_grouped"],
            "held_out_measurements": scored["held_out"]["measurements"],
            "changes": compare_changes(base["held_out"], scored["held_out"]),
            "accepted": held["precision"] >= 0.97
            and held["recall"] >= base["held_out"]["metrics"]["near"]["recall"] + 0.05,
        }
        if hard_manifest:
            hard, hard_features = load_manifest(hard_manifest)
            hard_vectors, hard_timings = service.encode(
                records_for_manifest(hard_manifest, hard, hard_features)
            )
            hard_results = {}
            for s in splits:
                ps = [p for split, p in hard_features if split == s]
                ls = [r for r in hard["pairs"] if r["split"] == s]
                baseline = score_split(SimilarityEngine(frozen), ps, ls)
                hybrid = score_split(
                    HybridEngine(frozen, selected, hard_vectors, service.identity), ps, ls
                )
                hard_results[s] = {
                    "baseline": metrics_row(baseline),
                    "hybrid": metrics_row(hybrid),
                    "changes": compare_changes(baseline, hybrid),
                }
            result["hard_benchmark"] = {
                "dataset_version": hard["dataset_version"],
                "results": hard_results,
                "timings": hard_timings,
            }
        result["original_benchmark_accepted"] = result["accepted"]
        if hard_manifest:
            result["accepted"] = (
                result["accepted"]
                and result["hard_benchmark"]["results"]["held_out"]["hybrid"]["precision"] >= 0.97
            )
        report["models"][model] = result
    accepted = [(name, result) for name, result in report["models"].items() if result["accepted"]]
    report["recommendation"] = (
        max(accepted, key=lambda pair: (pair[1]["held_out"]["recall"], -pair[1]["weight_bytes"]))[0]
        if accepted
        else "disabled"
    )
    report["duration_seconds"] = time.perf_counter() - started
    report["selection_protocol"] = (
        "Development precision >=98%, maximize recall; fixed threshold grid. "
        "Held-out acceptance >=97% precision and +5 percentage points recall. "
        "Hard set is supplemental, no retuning."
    )
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--hard-manifest", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            evaluate_hybrid(args.manifest, args.cache_dir, args.hard_manifest), sort_keys=True
        )
    )
