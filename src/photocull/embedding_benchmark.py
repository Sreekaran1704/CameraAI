"""Fresh child processes, cold inference versus warm cached hybrid analysis."""

import json
import os
import platform
import resource
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import ImageEnhance

from photocull.cache import Cache
from photocull.config import Config, EmbeddingConfig
from photocull.duplicate_evaluation import scene
from photocull.pipeline import run_sync


def one_benchmark(size, model, model_cache, selected):
    with tempfile.TemporaryDirectory(prefix="photocull-embedding-benchmark-") as temporary:
        root = Path(temporary).resolve()
        photos = root / "photos"
        photos.mkdir()
        cache = Cache(root / "cache")
        for suffix in ("pt", "json"):
            os.link(
                model_cache / "models" / f"{model}.{suffix}",
                cache.root / "models" / f"{model}.{suffix}",
            )
        base = None
        for i in range(size):
            if i % 10 == 0:
                base = scene(180704 + i)
            if i % 10 in (0, 1):
                base.save(photos / f"{i:05d}.png")
            elif i % 10 == 2:
                base.save(photos / f"{i:05d}.jpg", quality=65)
            elif i % 10 == 3:
                base.resize((192, 192)).save(photos / f"{i:05d}.png")
            elif i % 10 == 4:
                ImageEnhance.Brightness(base).enhance(1.10).save(photos / f"{i:05d}.png")
            else:
                scene(280704 + i).save(photos / f"{i:05d}.png")
        config = Config(cache_dir=cache.root, embeddings=EmbeddingConfig(**selected))
        cold = run_sync(photos, config)
        warm = run_sync(photos, config)
        cold_dup, warm_dup = cold["duplicates"], warm["duplicates"]
        stats, warm_stats = cold_dup["embeddings"], warm_dup["embeddings"]
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return {
            "images": size,
            "model": model,
            "cold_total_seconds": cold["timings"]["total"],
            "cold_embedding": stats,
            "warm_embedding": warm_stats,
            "cold_detection_including_embeddings_seconds": cold_dup["duration_seconds"],
            "cold_grouping_excluding_embedding_service_seconds": max(
                0, cold_dup["duration_seconds"] - stats["total_seconds"]
            ),
            "warm_detection_seconds": warm_dup["duration_seconds"],
            "warm_total_seconds": warm["timings"]["total"],
            "warm_detection_cache_hit": warm_dup["cache_hit"],
            "candidate_pairs": cold_dup["statistics"]["candidate_pairs"],
            "expensive_comparisons": cold_dup["statistics"]["expensive_comparisons"],
            "retrieval_comparisons": cold_dup["statistics"].get("retrieval_comparisons", 0),
            "budget_limited": cold_dup["statistics"]["budget_limited"],
            "peak_process_rss_mib": rss / (1024**2 if sys.platform == "darwin" else 1024),
            "cache_size": cache.status()["derived_bytes"],
            "database_bytes": (cache.root / "metadata.db").stat().st_size,
            "scope": (
                "Fresh process including imports, synthetic generation, cold and warm pipeline; "
                "256px fixtures, warm OS caches"
            ),
        }


def benchmark_embeddings(model_cache, evaluation_path):
    report = json.loads(evaluation_path.read_text())
    results = []
    for model, result in report["models"].items():
        for size in (100, 500, 1000):
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "photocull.embedding_benchmark",
                    "--size",
                    str(size),
                    "--model",
                    model,
                    "--model-cache",
                    str(model_cache),
                    "--selected",
                    json.dumps(result["selected_config"]),
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=600,
            )
            results.append(json.loads(process.stdout))
    return {
        "measurements": results,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "fixture_seeds": [180704, 280704],
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--size", type=int)
    parser.add_argument("--model")
    parser.add_argument("--model-cache", type=Path, required=True)
    parser.add_argument("--selected")
    parser.add_argument("--evaluation", type=Path)
    args = parser.parse_args()
    if args.evaluation:
        result = benchmark_embeddings(args.model_cache, args.evaluation)
    else:
        result = one_benchmark(args.size, args.model, args.model_cache, json.loads(args.selected))
    print(json.dumps(result, sort_keys=True))
