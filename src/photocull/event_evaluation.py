"""Family-separated synthetic event evaluation, real local image embeddings."""

import json
import resource
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from itertools import combinations
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance

from photocull.cache import Cache
from photocull.config import EventConfig, parameter_hash
from photocull.duplicate_evaluation import scene
from photocull.embeddings import EmbeddingService
from photocull.events import discover
from photocull.similarity import PhotoFeatures


def peak_memory_mib():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (
        2**20 if sys.platform == "darwin" else 1024
    )


CATEGORIES = (
    "ordinary",
    "close_occasions",
    "long_gap",
    "travel",
    "similar_different_days",
    "weak_timestamps",
    "missing_timestamps",
    "screenshots",
    "visual_outlier",
    "mixed_cameras",
)


def generate_events(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if any(folder.iterdir()):
        raise ValueError("Event fixture directory must be empty")
    rows = []
    for split, seed in (("dev", 41704), ("test", 91704)):
        for family_index in range(20):
            category = CATEGORIES[family_index % len(CATEGORIES)]
            family = f"{split}-{family_index:02d}"
            base = datetime(2025, 1, 1, 10, tzinfo=UTC) + timedelta(days=family_index * 3)
            first = scene(seed + family_index)
            # Different coarse composition, not merely a differently colored duplicate.
            rng = np.random.default_rng(seed + family_index)
            second = Image.new("RGB", (256, 256), tuple(int(v) for v in rng.integers(10, 65, 3)))
            draw = ImageDraw.Draw(second)
            for j in range(6):
                draw.ellipse(
                    (j * 30, 60, j * 30 + 65, 190),
                    fill=(int(rng.integers(140, 230)), 80 + j * 20, int(rng.integers(10, 65))),
                )
            for event_index in range(2):
                offsets = [0, 3, 6, 9, 12, 15]
                if category == "long_gap" and event_index == 0:
                    offsets = [0, 5, 10, 105, 110, 115]
                start = 25 if category == "close_occasions" else 360
                if category == "similar_different_days":
                    start = 1440
                for index, offset in enumerate(offsets):
                    identifier = f"{family}-{event_index}-{index}"
                    true_event = f"{family}-event-{event_index}"
                    minutes = offset + (start if event_index else 0)
                    capture = (base + timedelta(minutes=minutes)).isoformat()
                    filesystem = None
                    image = first.copy() if event_index == 0 else second.copy()
                    if category == "similar_different_days":
                        image = first.copy()
                    if category == "travel" and index >= 3:
                        image = second.copy() if event_index == 0 else first.copy()
                    image = ImageEnhance.Brightness(image).enhance(0.94 + index * 0.02)
                    if category == "weak_timestamps":
                        if event_index == 0:
                            filesystem, capture = capture, None
                        else:
                            capture = (
                                datetime.fromisoformat(capture).replace(tzinfo=None).isoformat()
                            )
                    if category == "missing_timestamps" and event_index == 0:
                        capture = None
                    if category == "mixed_cameras" and index >= 3:
                        capture = datetime.fromisoformat(capture).replace(tzinfo=None).isoformat()
                    path = folder / f"{identifier}.png"
                    exif = Image.Exif()
                    if capture:
                        parsed = datetime.fromisoformat(capture)
                        exif[36867] = parsed.strftime("%Y:%m:%d %H:%M:%S")
                        if parsed.tzinfo:
                            exif[36881] = "+00:00"
                    image.save(path, exif=exif)
                    rows.append(
                        {
                            "id": identifier,
                            "family": family,
                            "split": split,
                            "category": category,
                            "true_event": true_event,
                            "capture_time": capture,
                            "filesystem_time": filesystem,
                            "path": path.name,
                        }
                    )
            if category in {"screenshots", "visual_outlier"}:
                identifier = f"{family}-noise"
                image = Image.new("RGB", (256, 256), "white")
                draw = ImageDraw.Draw(image)
                for j in range(12):
                    draw.text((15, 12 + j * 18), f"Status message {j}", fill="black")
                path = folder / f"{identifier}.png"
                image.save(path)
                capture = (base + timedelta(minutes=8)).isoformat()
                rows.append(
                    {
                        "id": identifier,
                        "family": family,
                        "split": split,
                        "category": category,
                        "true_event": None,
                        "capture_time": capture if category == "visual_outlier" else None,
                        "filesystem_time": capture if category == "screenshots" else None,
                        "path": path.name,
                    }
                )
    manifest = {
        "version": "event_fixture_v2",
        "seed_dev": 41704,
        "seed_test": 91704,
        "photos": rows,
        "split_unit": "entire capture family / image seed",
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def load_events(manifest_path):
    from photocull.hashing import PerceptualHashService

    manifest = json.loads(Path(manifest_path).read_text())
    photos = []
    records = []
    for row in manifest["photos"]:
        path = Path(manifest_path).parent / row["path"]
        image_bytes = path.read_bytes()
        fp = parameter_hash(
            {"image_sha": __import__("hashlib").sha256(image_bytes).hexdigest(), "id": row["id"]}
        )
        with Image.open(path) as image:
            hashes = PerceptualHashService().analyze(image)
        photos.append(
            PhotoFeatures(
                row["id"],
                fp,
                fp,
                256,
                256,
                len(image_bytes),
                hashes,
                {"technical_quality_v1": 0.5},
                capture_time=row["capture_time"],
                filesystem_time=row["filesystem_time"],
            )
        )

        def loader(path=path):
            with Image.open(path) as image:
                return image.copy()

        records.append((row["id"], fp, loader))
    return manifest, photos, records


def metrics(rows, result):
    from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

    assigned = result["assignments"]
    truth = [r["true_event"] or f"noise:{r['id']}" for r in rows]
    predicted = [assigned[r["id"]]["event_id"] or f"unassigned:{r['id']}" for r in rows]
    tp = fp = fn = 0
    false_merges, false_splits = [], []
    for i, j in combinations(range(len(rows)), 2):
        same_truth = rows[i]["true_event"] is not None and truth[i] == truth[j]
        same_pred = assigned[rows[i]["id"]]["event_id"] is not None and predicted[i] == predicted[j]
        tp += same_truth and same_pred
        fp += not same_truth and same_pred
        fn += same_truth and not same_pred
        if same_pred and not same_truth and len(false_merges) < 40:
            false_merges.append(
                {"a": rows[i]["id"], "b": rows[j]["id"], "category": rows[i]["category"]}
            )
        if same_truth and not same_pred and len(false_splits) < 40:
            false_splits.append(
                {"a": rows[i]["id"], "b": rows[j]["id"], "category": rows[i]["category"]}
            )
    clusters = defaultdict(list)
    for true, predicted_id in zip(truth, predicted, strict=True):
        clusters[predicted_id].append(true)
    purity = sum(max(Counter(v).values()) for v in clusters.values()) / len(rows)
    counts = Counter(assigned[r["id"]]["status"] for r in rows)
    return {
        "ari": adjusted_rand_score(truth, predicted),
        "nmi": normalized_mutual_info_score(truth, predicted),
        "pairwise_precision": tp / (tp + fp) if tp + fp else 0,
        "pairwise_recall": tp / (tp + fn) if tp + fn else 0,
        "pairwise_f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "cluster_purity": purity,
        "true_event_count": len({r["true_event"] for r in rows if r["true_event"]}),
        "predicted_event_count": result["event_count"],
        "unassigned_rate": counts["UNASSIGNED"] / len(rows),
        "low_confidence_rate": counts["LOW_CONFIDENCE"] / len(rows),
        "noise_unassigned": sum(
            r["true_event"] is None and assigned[r["id"]]["status"] == "UNASSIGNED" for r in rows
        ),
        "noise_count": sum(r["true_event"] is None for r in rows),
        "errors": {"over_merge_examples": false_merges, "over_split_examples": false_splits},
    }


def evaluate_events(manifest_path, cache_dir):
    manifest, photos, records = load_events(manifest_path)
    assert not (
        {r["family"] for r in manifest["photos"] if r["split"] == "dev"}
        & {r["family"] for r in manifest["photos"] if r["split"] == "test"}
    )
    rows_by_split = {s: [r for r in manifest["photos"] if r["split"] == s] for s in ("dev", "test")}
    photo_by_split = {
        s: [p for p in photos if p.id in {r["id"] for r in rows_by_split[s]}] for s in rows_by_split
    }
    output = {
        "dataset_version": manifest["version"],
        "photo_count": len(photos),
        "families": 40,
        "categories": list(CATEGORIES),
        "experiments": [],
        "metric_convention": "Truth noise and predicted unassigned are individual singleton labels",
        "selection": "Development ARI, then pairwise precision, then lower dependency cost",
    }
    models = {}
    for model in ("mobilenet", "tinyclip"):
        service = EmbeddingService(Cache(cache_dir), model, "cpu", 16)
        vectors, cold = service.encode(records)
        _, warm = service.encode(records)
        models[model] = vectors
        output[model + "_embedding"] = {"identity": service.identity, "first": cold, "warm": warm}
    configs = [EventConfig(gap_minutes=g) for g in (15, 30, 60, 120, 240)]
    for model in models:
        for weight in (0.1, 0.3, 0.6):
            for eps in (0.15, 0.25, 0.4):
                configs.append(
                    EventConfig(
                        method="dbscan",
                        model=model,
                        time_weight=weight,
                        visual_weight=1 - weight,
                        epsilon=eps,
                    )
                )
        configs.append(EventConfig(method="hdbscan", model=model))
        configs.append(EventConfig(method="dbscan", model=model, pure_visual=True))
    for config in configs:
        vectors = models.get(config.model, {})
        result = discover(photo_by_split["dev"], config, vectors)
        scored = metrics(rows_by_split["dev"], result)
        output["experiments"].append(
            {
                "parameters": asdict(config),
                "dev": scored,
                "clustering_seconds": result["clustering_seconds"],
            }
        )
    finalists = []
    for model in ("disabled", "mobilenet", "tinyclip"):
        eligible = [
            e
            for e in output["experiments"]
            if e["parameters"]["model"] == model and not e["parameters"]["pure_visual"]
        ]
        best = max(eligible, key=lambda e: (e["dev"]["ari"], e["dev"]["pairwise_precision"]))
        config = EventConfig(**best["parameters"])
        result = discover(photo_by_split["test"], config, models.get(model, {}))
        score = metrics(rows_by_split["test"], result)
        categories = {}
        for category in CATEGORIES:
            selected_rows = [r for r in rows_by_split["test"] if r["category"] == category]
            # Retain full assignments; count only clusters represented in this category.
            subset = {
                **result,
                "event_count": len(
                    {
                        result["assignments"][r["id"]]["event_id"]
                        for r in selected_rows
                        if result["assignments"][r["id"]]["event_id"]
                    }
                ),
            }
            categories[category] = metrics(selected_rows, subset)
        finalist = {
            "model": model,
            "parameters": best["parameters"],
            "dev": best["dev"],
            "test": score,
            "test_categories": categories,
            "clustering_seconds": result["clustering_seconds"],
        }
        finalists.append(finalist)
    output["finalists"] = finalists
    best = max(
        finalists,
        key=lambda e: (e["dev"]["ari"], e["dev"]["pairwise_precision"], e["model"] == "disabled"),
    )
    baseline = finalists[0]
    material = (
        best["dev"]["ari"] - baseline["dev"]["ari"] >= 0.05
        and best["dev"]["pairwise_recall"] >= baseline["dev"]["pairwise_recall"] - 0.05
    )
    output["selected_default"] = best["parameters"] if material else baseline["parameters"]
    output["selection_reason"] = (
        "Visual ARI gain >=0.05 with recall loss <=0.05"
        if material
        else "Visual quality gain is modest or recall regresses; CPU/memory favor time segmentation"
    )
    output["peak_process_memory_mib"] = peak_memory_mib()
    return output


def metadata_records(count):
    photos = []
    vectors = {}
    rng = np.random.default_rng(81704)
    centers = rng.normal(size=(max(1, (count + 19) // 20), 64))
    for i in range(count):
        event = i // 20
        scalar = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(hours=event * 6, minutes=i % 20)
        identifier = str(i)
        photos.append(
            PhotoFeatures(
                identifier,
                parameter_hash({"i": i}),
                None,
                256,
                256,
                10000,
                {"phash": f"{i * 1000003:016x}"},
                {"technical_quality_v1": 0.5},
                scalar.isoformat(),
            )
        )
        vector = centers[event] + rng.normal(scale=0.05, size=64)
        vectors[identifier] = (vector / np.linalg.norm(vector)).astype(np.float32)
    return photos, vectors


def benchmark_metadata():
    rows = []
    for count in (100, 500, 1000, 5000):
        photos, vectors = metadata_records(count)
        for method in ("time", "dbscan", "hdbscan"):
            config = EventConfig(
                method=method, model="disabled" if method == "time" else "mobilenet"
            )
            started = time.perf_counter()
            result = discover(photos, config, vectors if method != "time" else {})
            rows.append(
                {
                    "records": count,
                    "method": method,
                    "seconds": time.perf_counter() - started,
                    "candidate_comparisons": result["candidate_comparisons"],
                    "events": result["event_count"],
                    "peak_memory_mib": peak_memory_mib(),
                    "embedding_cache_hit_rate": None if method == "time" else 1.0,
                    "embedding_reuse": (
                        "in-memory 64D synthetic metadata vectors; no image inference"
                    ),
                }
            )
    return rows
