"""Fresh-process, generated-fixture product benchmarks; never reads personal folders."""

import argparse
import hashlib
import json
import platform
import resource
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def deny(*args, **kwargs):
    raise AssertionError("Benchmark network disabled")


def peak():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (
        2**20 if sys.platform == "darwin" else 1024
    )


def child(mode, count):
    socket.socket.connect = deny
    socket.create_connection = deny
    started = time.perf_counter()
    from photocull.config import Config, DuplicateConfig, EventConfig, RankingConfig
    from photocull.events import discover
    from photocull.pipeline import run_sync
    from photocull.ranking import rank, shortlist
    from photocull.similarity import SimilarityEngine
    from photocull.sources import UploadedImageSource

    if mode != "local":
        import streamlit  # noqa: F401

        from photocull.ui.style import bundled_sources
        from photocull.web_session import DemoSession, add_sources
    imports = time.perf_counter() - started
    result = {
        "mode": mode,
        "records": count,
        "cold_import_seconds": imports,
        "demo_dataset_version": json.loads((ROOT / "assets/demo/manifest.json").read_text())[
            "version"
        ],
    }
    if mode == "local":
        import photocull.duplicates as duplicates
        import photocull.events as events
        import photocull.ranking_service as ranking

        timings = {}
        for module, name, label in (
            (duplicates, "detect_for_scan", "duplicates"),
            (events, "discover_for_scan", "events"),
            (ranking, "recommendations_for_scan", "ranking"),
        ):
            original = getattr(module, name)

            def measured(*args, _original=original, _label=label, **kwargs):
                start = time.perf_counter()
                value = _original(*args, **kwargs)
                timings[_label] = time.perf_counter() - start
                return value

            setattr(module, name, measured)
        assets = sorted((ROOT / "assets/demo").glob("*.jpg"))
        with tempfile.TemporaryDirectory(prefix="photocull-benchmark-") as directory:
            base = Path(directory).resolve()
            source = base / "generated"
            source.mkdir()
            for i in range(count):
                (source / f"fixture-{i:05d}.jpg").write_bytes(assets[i % len(assets)].read_bytes())
            digest = lambda: hashlib.sha256(  # noqa: E731
                b"".join(p.read_bytes() for p in sorted(source.iterdir()))
            ).hexdigest()
            before = digest()
            config = Config(cache_dir=base / "cache")
            for kind in ("cold", "warm"):
                start = time.perf_counter()
                run = run_sync(source, config)
                assert run["analyzed"] == count and run["failures"] == 0
                result[kind] = {
                    "wall_seconds": time.perf_counter() - start,
                    **run["timings"],
                    **timings,
                    "cache_hits": run["cache_hits"],
                    "cache_hit_rate": run["cache_hits"] / count,
                    "embedding_seconds": None,
                    "embedding_status": "disabled",
                }
            result["originals_unchanged"] = before == digest()
            result["thumbnail_bytes"] = sum(
                p.stat().st_size for p in (base / "cache/thumbnails").glob("*.jpg")
            )
            result["cache_bytes"] = sum(
                p.stat().st_size for p in (base / "cache").rglob("*") if p.is_file()
            )
            result["scope"] = "Current bundled JPEGs, cyclic sample copies; disk cache"
    else:
        sources = bundled_sources()
        session = DemoSession()
        if mode == "web":
            uploads = [
                UploadedImageSource(f"fixture-{i:02d}.jpg", sources[i % len(sources)].data)
                for i in range(count)
            ]
            start = time.perf_counter()
            add_sources(session, uploads)
            result["cold"] = {
                "wall_seconds": time.perf_counter() - start,
                **session.timings,
                "embedding_seconds": None,
                "embedding_status": "disabled; no model runtime",
            }
            start = time.perf_counter()
            session.analyze()
            result["warm"] = {
                "wall_seconds": time.perf_counter() - start,
                "decode": 0,
                "quality": 0,
                "hashing": 0,
                "thumbnail": 0,
                **{k: session.timings[k] for k in ("duplicates", "events", "ranking")},
                "memory_feature_reuse_rate": 1,
            }
            result["thumbnail_bytes"] = sum(map(len, session.thumbnails.values()))
            result["cache_bytes"] = 0
            result["upload_bytes"] = session.total_upload_bytes
            result["scope"] = "Current bundled JPEGs; memory-only core, excludes HTTP rendering"
        else:
            add_sources(session, sources)
            photos = [
                replace(
                    session.photos[i % len(session.photos)],
                    id=f"metadata-{i:05d}",
                    fingerprint=f"fingerprint-{i}",
                    sha256=f"sha-{i}",
                )
                for i in range(count)
            ]
            start = time.perf_counter()
            detection = SimilarityEngine(DuplicateConfig()).detect(photos)
            duplicate_time = time.perf_counter() - start
            start = time.perf_counter()
            discover(photos, EventConfig())
            event_time = time.perf_counter() - start
            start = time.perf_counter()
            ranked = rank(photos, RankingConfig())
            shortlist(photos, ranked["ranked"], 20, RankingConfig(), groups=detection["groups"])
            result["stages"] = {
                "duplicates": duplicate_time,
                "events": event_time,
                "ranking": time.perf_counter() - start,
            }
            result["duplicate_statistics"] = detection["statistics"]
            result["scope"] = "5000 cyclic scalar/hash metadata rows from 12 generated images"
        session.clear()
    result["peak_rss_mib"] = peak()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["local", "web", "metadata"])
    parser.add_argument("--count", type=int)
    args = parser.parse_args()
    if args.mode:
        print(json.dumps(child(args.mode, args.count), allow_nan=False))
        return
    measurements = []
    for mode, count in [
        ("local", 100),
        ("local", 500),
        ("local", 1000),
        ("metadata", 5000),
        ("web", 10),
        ("web", 20),
        ("web", 30),
    ]:
        completed = subprocess.run(
            [sys.executable, __file__, "--mode", mode, "--count", str(count)],
            capture_output=True,
            text=True,
            check=True,
        )
        measurement = json.loads(completed.stdout)
        measurements.append(measurement)
        print(f"{mode} {count}: {measurement['peak_rss_mib']:.1f} MiB", flush=True)
        (ROOT / "benchmarks/phase7-performance.json").write_text(
            json.dumps(
                {
                    "platform": platform.platform(),
                    "python": platform.python_version(),
                    "network_denied": True,
                    "method": "Fresh child process per size; one trial; no human photos",
                    "startup_scope": (
                        "Cold Python module imports, excludes interpreter and HTTP startup"
                    ),
                    "measurements": measurements,
                },
                indent=2,
            )
            + "\n"
        )


if __name__ == "__main__":
    main()
