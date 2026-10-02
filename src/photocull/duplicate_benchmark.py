"""Measured 100/500/1000-image generated collections, isolated process peak RSS."""

import json
import platform
import resource
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import ImageEnhance

from photocull.config import Config
from photocull.duplicate_evaluation import scene
from photocull.pipeline import run_sync


def one_benchmark(size):
    with tempfile.TemporaryDirectory(prefix="photocull-duplicates-benchmark-") as temporary:
        root = Path(temporary).resolve()
        photos = root / "photos"
        photos.mkdir()
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
        config = Config(cache_dir=root / "cache")
        cold = run_sync(photos, config)
        warm = run_sync(photos, config)
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak_mib = rss / (1024**2 if sys.platform == "darwin" else 1024)
        return {
            "images": size,
            "cold_total_seconds": cold["timings"]["total"],
            "cold_detection_seconds": cold["duplicates"]["duration_seconds"],
            "warm_total_seconds": warm["timings"]["total"],
            "warm_detection_seconds": warm["duplicates"]["duration_seconds"],
            "warm_detection_cache_hit": warm["duplicates"]["cache_hit"],
            "warm_photo_cache_hits": warm["cache_hits"],
            "candidate_pairs": cold["duplicates"]["statistics"]["candidate_pairs"],
            "expensive_comparisons": cold["duplicates"]["statistics"]["expensive_comparisons"],
            "budget_limited": cold["duplicates"]["statistics"]["budget_limited"],
            "peak_process_rss_mib": peak_mib,
            "peak_scope": "Entire fresh process including scans, grouping, caches and warm pass",
        }


def benchmark_duplicates():
    results = []
    for size in (100, 500, 1000):
        process = subprocess.run(
            [sys.executable, "-m", "photocull.duplicate_benchmark", str(size)],
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
        )
        results.append(json.loads(process.stdout))
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "seed": [180704, 280704],
        "fixture_edge": 256,
        "measurements": results,
        "limitations": "Generated geometric images, warm OS caches; not camera-roll latency.",
    }


if __name__ == "__main__":
    print(json.dumps(one_benchmark(int(sys.argv[1])), sort_keys=True))
