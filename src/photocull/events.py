"""Bounded local event discovery. Independent of duplicate classification."""

import time
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from photocull.config import EventConfig, parameter_hash
from photocull.similarity import group_signature, timestamp

VERSION = "event_clustering_v1"
CONFIDENCE = {
    "exif_timezone": "high",
    "exif_naive": "medium",
    "filesystem": "low",
    "unknown": "none",
}


def clock(photo):
    value, tier = timestamp(photo)
    if value is None:
        return None, tier, "unknown"
    # Never interpret a naive timestamp in the machine's local timezone.
    aware = value.tzinfo is not None
    scalar = (value.astimezone(UTC).replace(tzinfo=None) if aware else value) - datetime(1970, 1, 1)
    return scalar.total_seconds(), tier, "aware" if aware else "naive"


def segments(photos, gap_seconds, max_span_seconds):
    partitions = defaultdict(list)
    missing = []
    for photo in photos:
        scalar, tier, awareness = clock(photo)
        if scalar is None:
            missing.append(photo)
        else:
            partitions[tier, awareness].append((scalar, photo))
    output = []
    for key in sorted(partitions):
        current = []
        for scalar, photo in sorted(partitions[key], key=lambda v: (v[0], v[1].id)):
            if current and (
                scalar - current[-1][0] > gap_seconds or scalar - current[0][0] > max_span_seconds
            ):
                output.append([p for _, p in current])
                current = []
            current.append((scalar, photo))
        if current:
            output.append([p for _, p in current])
    return output, missing


def normalize_vectors(vectors):
    output = {}
    dimension = None
    for identifier, vector in vectors.items():
        value = np.asarray(vector, dtype=np.float32)
        if value.ndim != 1 or not np.isfinite(value).all() or np.linalg.norm(value) <= 1e-9:
            raise ValueError("Invalid event embedding")
        if dimension is not None and value.size != dimension:
            raise ValueError("Mixed embedding dimensions")
        dimension = value.size
        output[str(identifier)] = value / np.linalg.norm(value)
    return output


def representatives(members, vectors=None):
    """Centroid-medoid approximation; quality breaks ties, hashes suppress repetition."""
    vectors = vectors or {}
    available = [p for p in members if p.id in vectors]
    center = np.mean([vectors[p.id] for p in available], axis=0) if available else None
    if center is not None and np.linalg.norm(center) > 1e-9:
        center = center / np.linalg.norm(center)
    known_times = [clock(p)[0] for p in members if clock(p)[0] is not None]
    temporal_center = float(np.median(known_times)) if known_times else None

    def centrality(photo):
        if photo.id in vectors and center is not None:
            return -float(np.dot(vectors[photo.id], center))
        value = clock(photo)[0]
        return abs(value - temporal_center) if value is not None else float("inf")

    ordered = sorted(
        members, key=lambda p: (centrality(p), -p.quality.get("technical_quality_v1", 0), p.id)
    )
    chosen = []
    for photo in ordered:
        repetitive = any(
            (photo.sha256 and photo.sha256 == other.sha256)
            or (
                photo.hashes.get("phash")
                and other.hashes.get("phash")
                and (int(photo.hashes["phash"], 16) ^ int(other.hashes["phash"], 16)).bit_count()
                <= 2
            )
            for other in chosen
        )
        if not repetitive:
            chosen.append(photo)
        if len(chosen) == 3:
            break
    return [p.id for p in chosen]


def event_record(members, vectors=None, identifier=None, name=None, manual=False):
    known = sorted(
        (clock(p)[0], p.id, timestamp(p)[0].isoformat()) for p in members if clock(p)[0] is not None
    )
    return {
        "id": identifier or "auto-" + group_signature(members),
        "name": name,
        "members": sorted(p.id for p in members),
        "start": known[0][2] if known else None,
        "end": known[-1][2] if known else None,
        "representatives": representatives(members, vectors),
        "representative_reason": "centroid medoid approximation + TechnicalQualityv1 tie-break"
        if vectors
        else "temporal center + TechnicalQualityv1 tie-break",
        "manual": manual,
    }


def discover(photos, config=None, vectors=None, cancelled=lambda: False):
    config = config or EventConfig()
    vectors = normalize_vectors(vectors or {})
    started = time.perf_counter()
    if len({p.id for p in photos}) != len(photos):
        raise ValueError("Event photo IDs must be unique")
    groups, missing = segments(
        photos,
        (config.gap_minutes if config.method == "time" else config.coarse_gap_minutes) * 60,
        config.max_span_hours * 3600,
    )
    if config.pure_visual and config.method != "time":
        groups, missing = [sorted(photos, key=lambda p: p.id)], []
    assignments = {}
    clusters = []
    comparisons = 0
    truncated = False
    warnings = []
    for photo in missing:
        assignments[photo.id] = assignment(photo, None, "UNASSIGNED", "No usable timestamp")
    for group in groups:
        group_truncated = False
        if cancelled():
            raise InterruptedError("Event discovery cancelled")
        if config.method == "time":
            labels = np.zeros(len(group), dtype=int)
        else:
            valid = [p for p in group if p.id in vectors]
            for p in group:
                if p.id not in vectors:
                    assignments[p.id] = assignment(
                        p, None, "UNASSIGNED", "Local embedding unavailable"
                    )
            group = valid
            if not group:
                continue
            if len(group) == 1:
                labels = np.array([-1])
            elif config.method == "hdbscan":
                from sklearn.cluster import HDBSCAN

                if len(group) > config.hdbscan_window_limit:
                    warnings.append("HDBSCAN window exceeds bounded limit; left for review")
                    labels = np.full(len(group), -1)
                else:
                    # Euclidean feature space is a distinct evaluated HDBSCAN alternative.
                    t0 = clock(group[0])[0] or 0
                    temporal = np.array(
                        [
                            ((clock(p)[0] or t0) - t0) / (config.coarse_gap_minutes * 60)
                            for p in group
                        ]
                    )
                    matrix = np.array([vectors[p.id] for p in group])
                    features = np.column_stack(
                        (
                            matrix * np.sqrt(config.visual_weight / 2),
                            temporal * np.sqrt(0 if config.pure_visual else config.time_weight),
                        )
                    )
                    labels = HDBSCAN(
                        min_cluster_size=max(2, config.min_samples),
                        min_samples=config.min_samples,
                        allow_single_cluster=True,
                        copy=True,
                    ).fit_predict(features)
                    comparisons += len(group) * (len(group) - 1) // 2
            else:
                from scipy.sparse import csr_matrix
                from sklearn.cluster import DBSCAN
                from sklearn.neighbors import sort_graph_by_row_values

                # Sparse, time-ordered bounded neighborhood. No N x N matrix.
                row, col, distances = (
                    list(range(len(group))),
                    list(range(len(group))),
                    [1e-8] * len(group),
                )
                for i, left in enumerate(group):
                    end = min(len(group), i + 1 + config.candidate_neighbors)
                    if end < len(group):
                        truncated = True
                        group_truncated = True
                    for j in range(i + 1, end):
                        right = group[j]
                        delta = abs((clock(left)[0] or 0) - (clock(right)[0] or 0))
                        temporal = delta / (config.coarse_gap_minutes * 60)
                        if not config.pure_visual and temporal > 1:
                            break
                        comparisons += 1
                        visual = max(0, 1 - float(np.dot(vectors[left.id], vectors[right.id])))
                        distance = config.visual_weight * visual
                        if not config.pure_visual:
                            distance += config.time_weight * temporal
                        if distance <= config.epsilon:
                            row.extend((i, j))
                            col.extend((j, i))
                            distances.extend((max(distance, 1e-8),) * 2)
                graph = csr_matrix((distances, (row, col)), shape=(len(group), len(group)))
                graph = sort_graph_by_row_values(graph, warn_when_not_sorted=False)
                labels = DBSCAN(
                    eps=config.epsilon, min_samples=config.min_samples, metric="precomputed"
                ).fit_predict(graph)
        for label in sorted(set(labels)):
            members = [p for p, predicted in zip(group, labels, strict=True) if predicted == label]
            if label < 0:
                for photo in members:
                    assignments[photo.id] = assignment(
                        photo,
                        None,
                        "UNASSIGNED",
                        "Insufficient local density / isolated visual outlier",
                    )
                continue
            event = event_record(members, vectors)
            clusters.append(event)
            for photo in members:
                _, tier, _ = clock(photo)
                low = tier != "exif_timezone" or group_truncated
                assignments[photo.id] = assignment(
                    photo,
                    event["id"],
                    "LOW_CONFIDENCE" if low else "EVENT_MEMBER",
                    "Filesystem timestamp can reflect copying"
                    if tier == "filesystem"
                    else "EXIF has no timezone; camera clocks may differ"
                    if tier == "exif_naive"
                    else "Bounded neighbor search; dense window requires review"
                    if group_truncated
                    else "Temporal continuity"
                    if config.method == "time"
                    else "Temporal window and local visual density",
                )
    clusters.sort(key=lambda e: (e["start"] or "", e["id"]))
    for index, event in enumerate(clusters, 1):
        event["name"] = f"Event {index:02d}"
    return {
        "version": VERSION,
        "parameters": asdict(config),
        "events": clusters,
        "assignments": assignments,
        "candidate_comparisons": comparisons,
        "comparison_count_kind": (
            "window pair upper bound"
            if config.method == "hdbscan"
            else "enumerated candidate pairs"
        ),
        "candidate_search_truncated": truncated,
        "warnings": sorted(set(warnings)),
        "clustering_seconds": time.perf_counter() - started,
        "event_count": len(clusters),
        "unassigned_count": sum(a["status"] == "UNASSIGNED" for a in assignments.values()),
        "low_confidence_count": sum(a["status"] == "LOW_CONFIDENCE" for a in assignments.values()),
    }


def assignment(photo, event_id, status, reason):
    _, tier, awareness = clock(photo)
    return {
        "photo_id": photo.id,
        "fingerprint": photo.fingerprint,
        "event_id": event_id,
        "status": status,
        "reason": reason,
        "timestamp_tier": tier,
        "timestamp_confidence": CONFIDENCE[tier],
        "timestamp_awareness": awareness,
    }


def discover_for_scan(repository, scan_id, config, cancelled=lambda: False):
    from photocull.cache import Cache, refuse_symlinks
    from photocull.duplicates import features_from_rows
    from photocull.event_storage import EventStore
    from photocull.scanner import SourceChangedError, fingerprint

    cache = Cache(config.cache_dir)
    rows = repository.results(scan_id)
    photos = features_from_rows(rows, cache, verify=False)
    store = EventStore(repository)
    vectors, identity = {}, {}
    embedding_stats = {"enabled": False, "cache_hit_rate": None}
    selected = config.events
    if selected.method != "time":
        from photocull.embeddings import EmbeddingService, ModelUnavailable
        from photocull.scanner import PhotoScanner

        try:
            import sklearn  # noqa: F401 — validate optional event dependency before inference

            service = EmbeddingService(cache, selected.model, "cpu", 16, repository)
            identity = service.identity
            paths = {str(row["id"]): Path(row["path"]) for row in rows}
            records = []
            for photo in photos:

                def loader(path=paths[photo.id], expected=photo.fingerprint):
                    image, metadata = PhotoScanner().read(path, config.max_pixels)
                    if metadata["fingerprint"] != expected:
                        image.close()
                        raise SourceChangedError("Source changed before event embedding")
                    return image

                records.append((photo.id, photo.fingerprint, loader))
            vectors, embedding_stats = service.encode(records, cancelled)
            embedding_stats["enabled"] = True
        except (ModelUnavailable, ImportError) as exc:
            from dataclasses import replace

            selected = replace(selected, method="time", model="disabled", pure_visual=False)
            embedding_stats["warning"] = str(exc)
            embedding_stats["fallback"] = "time"
    from importlib.metadata import version

    runtime = {"numpy": version("numpy")}
    if selected.method != "time":
        runtime["scikit-learn"] = version("scikit-learn")
    analysis_id = repository.version(
        "EventDiscovery",
        VERSION,
        {"config": asdict(selected), "embedding": identity, "runtime": runtime},
    )
    key = parameter_hash(
        {
            "analysis": analysis_id,
            "photos": [
                (
                    p.id,
                    p.fingerprint,
                    p.source_versions,
                    p.capture_time,
                    p.capture_timezone,
                    p.filesystem_time,
                )
                for p in photos
            ],
        }
    )
    result = store.cached(key)
    hit = result is not None
    if not hit:
        result = discover(photos, selected, vectors, cancelled)
        sources = {str(row["id"]): row for row in rows}
        for photo in photos:
            source = sources[photo.id]
            if fingerprint(refuse_symlinks(Path(source["path"]))) != photo.fingerprint:
                raise SourceChangedError("Source changed during event grouping")
        result["analysis_id"] = analysis_id
        result["excluded_stale_or_incomplete"] = len(rows) - len(photos)
        store.save(key, result)
    store.link(scan_id, key)
    result = store.overlay(result, photos, vectors)
    return {**result, "cache_hit": hit, "embeddings": embedding_stats}
