"""Measured local cold/warm pipeline benchmark."""

import platform
import tempfile
from pathlib import Path

from photocull import __version__
from photocull.config import Config
from photocull.fixtures import FIXTURE_VERSION, generate_fixtures
from photocull.pipeline import run_sync


def benchmark(count=100):
    with tempfile.TemporaryDirectory(prefix="photocull-benchmark-") as temporary:
        root = Path(temporary).resolve()
        generate_fixtures(root / "photos", count)
        config = Config(cache_dir=root / "cache")
        cold = run_sync(root / "photos", config)
        warm = run_sync(root / "photos", config)
        return {
            "app_version": __version__,
            "fixture_version": FIXTURE_VERSION,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "config": {k: v for k, v in config.snapshot().items() if k != "cache_dir"},
            "cold": cold,
            "warm": warm,
            "cold_photos_per_second": cold["analyzed"] / cold["timings"]["total"],
            "warm_photos_per_second": warm["analyzed"] / warm["timings"]["total"],
        }
