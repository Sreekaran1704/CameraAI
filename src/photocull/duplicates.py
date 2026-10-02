"""Filesystem adapter; similarity/grouping itself accepts in-memory feature records."""

import json
import time
from pathlib import Path

from PIL import Image

from photocull.cache import Cache, refuse_symlinks
from photocull.duplicate_storage import DuplicateStore
from photocull.scanner import SourceChangedError, fingerprint
from photocull.similarity import PhotoFeatures, SimilarityEngine, verification_from_image


def features_from_rows(rows, cache=None, verify=True):
    photos = []
    for row in rows:
        if row["source_changed_since_run"] or not row["quality"] or not row["hashes"]:
            continue
        meta, q, hashes = row["metadata"], row["quality"], row["hashes"]
        try:
            source_stat = Path(meta["path"]).stat()
        except OSError:
            continue
        photo = PhotoFeatures(
            id=str(row["id"]),
            fingerprint=row["run_fingerprint"],
            sha256=row["content_sha256"],
            width=meta["width"],
            height=meta["height"],
            size=meta["file_size"],
            hashes={k: hashes[k] for k in ("phash", "dhash", "ahash")},
            quality={
                "raw": json.loads(q["raw_json"]),
                "normalized": json.loads(q["normalized_json"]),
                "technical_quality_v1": q["technical_quality_v1"],
            },
            capture_time=meta["capture_time"],
            capture_timezone=meta["capture_timezone"],
            filesystem_time=meta["filesystem_time"],
            filename=meta["filename"],
            storage_identity=f"{source_stat.st_dev}:{source_stat.st_ino}",
            link_count=source_stat.st_nlink,
            source_versions={
                "quality": q["analysis_id"],
                "hashes": hashes["analysis_id"],
                "thumbnail": row["thumbnail"]["analysis_id"] if row["thumbnail"] else None,
            },
        )
        if verify and row["thumbnail"]:
            try:
                path = refuse_symlinks(Path(row["thumbnail"]["path"]))
                if cache is not None and path.parent != cache.root / "thumbnails":
                    raise ValueError("Thumbnail outside application cache")
                with Image.open(path) as image:
                    photo.verification = verification_from_image(image)
            except (OSError, ValueError):
                # Exact file hashes remain usable; do not infer perceptual matches without pixels.
                photo.verification = None
        photos.append(photo)
    return photos


def detect_for_scan(repository, scan_id, config, cancelled=lambda: False):
    started = time.perf_counter()
    cache = Cache(config.cache_dir)
    rows = repository.results(scan_id)
    photos = features_from_rows(rows, cache, verify=False)
    store = DuplicateStore(repository)
    blocked, suppressed = store.corrections(photos)
    engine = SimilarityEngine(config.duplicates)
    embedding_stats = {"enabled": False}
    if config.embeddings.model != "disabled":
        from photocull.embeddings import EmbeddingService, ModelUnavailable
        from photocull.hybrid import HybridEngine
        from photocull.scanner import PhotoScanner

        try:
            service = EmbeddingService(
                cache,
                config.embeddings.model,
                config.embeddings.device,
                config.embeddings.batch_size,
                repository,
            )
            by_id = {str(r["id"]): r for r in rows}
            records = []
            for photo in photos:
                path = Path(by_id[photo.id]["metadata"]["path"])

                def loader(path=path, expected=photo.fingerprint):
                    image, metadata = PhotoScanner().read(path, config.max_pixels)
                    if metadata["fingerprint"] != expected:
                        image.close()
                        raise SourceChangedError("Source changed before embedding inference")
                    return image

                records.append((photo.id, photo.fingerprint, loader))
            vectors, embedding_stats = service.encode(records, cancelled)
            embedding_stats["enabled"] = True
            engine = HybridEngine(config.duplicates, config.embeddings, vectors, service.identity)
        except ModelUnavailable as exc:
            embedding_stats = {"enabled": False, "warning": str(exc), "fallback": "hash-only"}
    analysis_id = repository.version(engine.name, engine.version, engine.parameters)
    dataset_key = store.dataset_key(photos, blocked, suppressed)
    result = store.cached(analysis_id, dataset_key)
    if result:
        store.link(scan_id, result["duplicate_run_id"])
        return {
            **result,
            "cache_hit": True,
            "duration_seconds": time.perf_counter() - started,
            "embeddings": embedding_stats,
        }
    photos = features_from_rows(rows, cache)
    result = engine.detect(photos, blocked, suppressed, cancelled)
    if cancelled():
        raise InterruptedError("Duplicate detection cancelled")
    paths = {str(row["id"]): Path(row["metadata"]["path"]) for row in rows}
    for photo in photos:
        if fingerprint(refuse_symlinks(paths[photo.id])) != photo.fingerprint:
            raise SourceChangedError("Source changed during duplicate grouping; rescan required")
    result["eligible_photos"] = len(photos)
    result["verification_unavailable"] = sum(p.verification is None for p in photos)
    result["excluded_stale_or_incomplete"] = len(rows) - len(photos)
    result["embeddings"] = embedding_stats
    saved = store.save(scan_id, analysis_id, dataset_key, result, photos)
    return {
        **saved,
        "cache_hit": False,
        "duration_seconds": time.perf_counter() - started,
        "embeddings": embedding_stats,
    }
