"""Fresh-process event CPU benchmarks with real local cached embeddings."""

import json
import os
import platform
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import ImageEnhance

from photocull.cache import Cache
from photocull.config import EventConfig
from photocull.duplicate_evaluation import scene
from photocull.embeddings import EmbeddingService
from photocull.event_evaluation import metadata_records
from photocull.events import discover


def one(size, selected, model_cache):
    config = EventConfig(**selected)
    photos, _ = metadata_records(size)
    # Deterministic 20-photo occasions, all timestamps explicitly timezone aware.
    with tempfile.TemporaryDirectory(prefix="photocull-events-bench-") as temporary:
        root = Path(temporary).resolve()
        folder = root / "photos"
        folder.mkdir()
        records = []
        for index, photo in enumerate(photos):
            base = scene(61704 + index // 20)
            image = ImageEnhance.Brightness(base).enhance(0.9 + (index % 20) / 100)
            path = folder / f"{index}.png"
            image.save(path)

            def loader(path=path):
                from PIL import Image

                with Image.open(path) as image:
                    return image.copy()

            records.append((photo.id, photo.fingerprint, loader))
        cache = Cache(root / "cache")
        vectors = {}
        cold_stats, warm_stats = {"enabled": False}, {"enabled": False}
        before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        start = time.perf_counter()
        if config.model != "disabled":
            for suffix in ("pt", "json"):
                os.link(
                    model_cache / "models" / f"{config.model}.{suffix}",
                    cache.root / "models" / f"{config.model}.{suffix}",
                )
            service = EmbeddingService(cache, config.model, "cpu", 16)
            vectors, cold_stats = service.encode(records)
        cold = discover(photos, config, vectors)
        cold_total = time.perf_counter() - start
        start = time.perf_counter()
        if config.model != "disabled":
            vectors, warm_stats = service.encode(records)
        warm = discover(photos, config, vectors)
        return {
            "images": size,
            "model": config.model,
            "method": config.method,
            "parameters": selected,
            "cold_event_seconds": cold_total,
            "cold_clustering_seconds": cold["clustering_seconds"],
            "warm_event_seconds": time.perf_counter() - start,
            "warm_clustering_seconds": warm["clustering_seconds"],
            "cold_embeddings": cold_stats,
            "warm_embeddings": warm_stats,
            "candidate_comparisons": cold["candidate_comparisons"],
            "event_count": cold["event_count"],
            "peak_memory_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            / (2**20 if sys.platform == "darwin" else 1024),
            "pre_inference_peak_mib": before / (2**20 if sys.platform == "darwin" else 1024),
            "scope": (
                "Fresh process, 256px synthetic photos; no source scanning/quality/duplicate time"
            ),
        }


def run_benchmarks(evaluation, model_cache):
    report = json.loads(evaluation.read_text())
    measurements = []
    for finalist in report["finalists"]:
        for size in (30, 100, 500, 1000):
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "photocull.event_benchmark",
                    "--size",
                    str(size),
                    "--selected",
                    json.dumps(finalist["parameters"]),
                    "--model-cache",
                    str(model_cache),
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=600,
            )
            measurements.append(json.loads(process.stdout))
    return {
        "measurements": measurements,
        "platform": platform.platform(),
        "python": platform.python_version(),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--size", type=int)
    parser.add_argument("--selected")
    parser.add_argument("--evaluation", type=Path)
    parser.add_argument("--model-cache", type=Path, required=True)
    args = parser.parse_args()
    result = (
        run_benchmarks(args.evaluation, args.model_cache)
        if args.evaluation
        else one(args.size, json.loads(args.selected), args.model_cache)
    )
    print(json.dumps(result, allow_nan=False))
