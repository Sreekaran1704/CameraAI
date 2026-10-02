"""Cancellable pipeline independent of Streamlit's execution lifecycle."""

import json
import logging
import os
import time
from pathlib import Path

from photocull.cache import Cache, refuse_symlinks
from photocull.config import Config
from photocull.hashing import PerceptualHashService
from photocull.quality import QualityAnalyzer
from photocull.scanner import PhotoScanner, SourceChangedError, fingerprint
from photocull.storage import Repository
from photocull.thumbnails import ThumbnailService


def analyze_run(config: Config, run_id: str, thorough=False) -> dict:
    cache = Cache(config.cache_dir)
    repository = Repository(cache.root / "metadata.db")
    started = time.perf_counter()
    progress = {
        "discovered_photos": 0,
        "discovered_files": 0,
        "supported_files": 0,
        "unsupported_files": 0,
        "skipped_symlinks": 0,
        "processed": 0,
        "analyzed": 0,
        "failures": 0,
        "total_source_bytes": 0,
        "cache_hits": 0,
        "component_cache_hits": 0,
        "stage": "scanning",
        "timings": {
            "scanning": 0.0,
            "quality": 0.0,
            "hashing": 0.0,
            "thumbnail": 0.0,
            "total": 0.0,
        },
    }

    def update(status="running", finished=False):
        progress["timings"]["total"] = time.perf_counter() - started
        repository.update_run(run_id, status, progress, finished)

    try:
        with cache.lock():
            run = repository.get_run(run_id)
            if run["status"] not in {"queued", "interrupted"}:
                raise ValueError(
                    "Run has already started; create a fresh run to resume cached work"
                )
            root = Path(run["source_root"])
            cache.assert_source(root)
            with repository.db:
                repository.db.execute(
                    "UPDATE scan_runs SET worker_pid=? WHERE id=?", (os.getpid(), run_id)
                )
            scanner = PhotoScanner()
            quality = QualityAnalyzer(config.quality)
            hashes = PerceptualHashService()
            thumbnails = ThumbnailService(cache, config.thumbnail_edge, config.thumbnail_quality)
            ids = {
                service.name: repository.version(service.name, service.version, service.parameters)
                for service in (quality, hashes, thumbnails)
            }
            progress["analysis_ids"] = ids
            scan_start = time.perf_counter()
            candidates = []
            update()
            for kind, path in scanner.discover(root, lambda: repository.cancelled(run_id)):
                if kind == "discovery_error":
                    repository.failure(run_id, getattr(path, "filename", root), "discovery", path)
                    progress["failures"] += 1
                elif kind == "symlink":
                    progress["skipped_symlinks"] += 1
                else:
                    progress["discovered_files"] += 1
                    progress[f"{kind}_files"] += 1
                    if kind == "supported":
                        progress["discovered_photos"] += 1
                        candidates.append(path)
                        try:
                            progress["total_source_bytes"] += path.stat().st_size
                        except OSError:
                            pass  # Recorded with file context during processing.
                if (progress["discovered_files"] + progress["skipped_symlinks"]) % 25 == 0:
                    update()
            progress["timings"]["scanning"] = time.perf_counter() - scan_start
            progress["stage"] = "processing"
            update()
            for path in candidates:
                if repository.cancelled(run_id):
                    break
                stage = "metadata"
                image = None
                try:
                    refuse_symlinks(path)
                    current = fingerprint(path)
                    source = repository.source(path)
                    if source and source["fingerprint"] == current:
                        existing = json.loads(source["metadata_json"])
                        if existing["width"] * existing["height"] > config.max_pixels:
                            raise ValueError("Image exceeds configured pixel limit")
                    reuse_source = bool(
                        source and source["fingerprint"] == current and not thorough
                    )
                    cached = {}
                    if reuse_source:
                        for table, component in (
                            ("quality_measurements", quality.name),
                            ("perceptual_hashes", hashes.name),
                            ("thumbnail_metadata", thumbnails.name),
                        ):
                            cached[component] = repository.cached(
                                table, source["id"], current, ids[component]
                            )
                        thumb = cached[thumbnails.name]
                        if thumb and (
                            Path(thumb["path"])
                            != cache.root / "thumbnails" / f"{thumbnails.key(current)}.jpg"
                            or not refuse_symlinks(Path(thumb["path"])).is_file()
                        ):
                            cached[thumbnails.name] = None
                    scan_start = time.perf_counter()
                    if not reuse_source or not all(cached.values()) or run["mode"] == "scan":
                        image, metadata = scanner.read(
                            path, config.max_pixels, full_hash=not reuse_source
                        )
                        if reuse_source:
                            metadata["content_sha256"] = source["content_sha256"]
                        photo_id = repository.save_source(metadata)
                    else:
                        photo_id = source["id"]
                        metadata = json.loads(source["metadata_json"])
                    progress["timings"]["scanning"] += time.perf_counter() - scan_start
                    if run["mode"] == "analyze":
                        for service, key, saver in (
                            (quality, "quality", repository.save_quality),
                            (hashes, "hashing", repository.save_hashes),
                            (thumbnails, "thumbnail", repository.save_thumbnail),
                        ):
                            stage = key
                            if cached.get(service.name):
                                progress["component_cache_hits"] += 1
                                continue
                            phase_start = time.perf_counter()
                            result = (
                                service.generate(image, current)
                                if key == "thumbnail"
                                else service.analyze(image)
                            )
                            if fingerprint(path) != current:
                                raise SourceChangedError("Source changed during analysis")
                            saver(photo_id, current, ids[service.name], result)
                            progress["timings"][key] += time.perf_counter() - phase_start
                    if fingerprint(path) != current:
                        raise SourceChangedError("Source changed before completion")
                    repository.attach(run_id, photo_id, current)
                    if run["mode"] == "analyze":
                        if cached and all(cached.values()):
                            progress["cache_hits"] += 1
                        progress["analyzed"] += 1
                except Exception as exc:
                    repository.failure(run_id, path, stage, exc)
                    progress["failures"] += 1
                    logging.getLogger("photocull").warning(
                        "File processing failed at %s: %s", stage, type(exc).__name__
                    )
                finally:
                    if image is not None:
                        image.close()
                progress["processed"] += 1
                update()
            progress["stage"] = "finished"
            if run["mode"] == "analyze" and not repository.cancelled(run_id):
                from photocull.duplicates import detect_for_scan

                progress["stage"] = "duplicate detection"
                update()
                try:
                    detection = detect_for_scan(
                        repository, run_id, config, lambda: repository.cancelled(run_id)
                    )
                    progress["duplicates"] = {
                        k: v for k, v in detection.items() if k not in {"groups", "pairs"}
                    }
                except InterruptedError:
                    pass
            if run["mode"] == "analyze" and not repository.cancelled(run_id):
                from photocull.events import discover_for_scan

                progress["stage"] = "event discovery"
                update()
                try:
                    events = discover_for_scan(
                        repository, run_id, config, lambda: repository.cancelled(run_id)
                    )
                    progress["events"] = {
                        k: v for k, v in events.items() if k not in {"events", "assignments"}
                    }
                except InterruptedError:
                    pass
            if run["mode"] == "analyze" and not repository.cancelled(run_id):
                from photocull.ranking_service import recommendations_for_scan

                progress["stage"] = "photo ranking"
                update()
                progress["ranking"] = recommendations_for_scan(repository, run_id, config)
            progress["stage"] = "finished"
            update("cancelled" if repository.cancelled(run_id) else "completed", True)
    except Exception as exc:
        repository.failure(run_id, None, "pipeline", exc)
        progress["failures"] += 1
        update("failed", True)
    finally:
        repository.close()
    return progress


def run_sync(root: Path, config: Config, mode="analyze", thorough=False):
    cache = Cache(config.cache_dir)
    cache.assert_source(root)
    repository = Repository(cache.root / "metadata.db")
    try:
        run_id = repository.create_run(root, mode, config.snapshot())
    finally:
        repository.close()
    progress = analyze_run(config, run_id, thorough)
    return {"run_id": run_id, **progress}
