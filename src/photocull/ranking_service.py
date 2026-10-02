"""Versioned ranking adapter. Reads existing vectors; never performs inference."""

import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from photocull.cache import Cache, refuse_symlinks
from photocull.config import parameter_hash
from photocull.duplicate_storage import DuplicateStore
from photocull.duplicates import features_from_rows
from photocull.embeddings import CHECKSUMS, MODELS
from photocull.event_storage import EventStore
from photocull.ranking import VERSION, rank, shortlist
from photocull.similarity import group_signature

MIGRATION_5 = """
BEGIN IMMEDIATE;
CREATE TABLE ranking_results (
 cache_key TEXT PRIMARY KEY, analysis_id TEXT NOT NULL REFERENCES analysis_versions(id),
 result_json TEXT NOT NULL
);
PRAGMA user_version=5;
COMMIT;
"""


def cached_vectors(repo, cache, photos, model):
    if model == "disabled":
        return {}, {"model": model, "requested": 0, "hits": 0, "cache_hit_rate": None}
    vectors, identities = {}, set()
    by_id = {p.id: p for p in photos}
    spec = MODELS[model]
    records = repo.db.execute(
        "SELECT * FROM embedding_records WHERE model_id=? ORDER BY generated_at DESC", (model,)
    )
    for row in records:
        identifier = str(row["photo_id"])
        if (
            identifier not in by_id
            or identifier in vectors
            or row["fingerprint"] != by_id[identifier].fingerprint
            or row["checksum"] != CHECKSUMS[model]
            or row["preprocessing"] != spec.preprocessing
        ):
            continue
        try:
            path = refuse_symlinks(Path(row["path"]))
            if path != cache.root / "embeddings" / f"{row['cache_key']}.npy":
                continue
            vector = np.load(path, allow_pickle=False)
            if (
                vector.shape != (spec.dimension,)
                or not np.isfinite(vector).all()
                or abs(float(np.linalg.norm(vector)) - 1) > 1e-4
            ):
                continue
            vectors[identifier] = vector
            identities.add(row["analysis_id"])
        except (ValueError, OSError):
            continue
    return vectors, {
        "model": model,
        "requested": len(photos),
        "hits": len(vectors),
        "cache_hit_rate": len(vectors) / len(photos) if photos else None,
        "analysis_ids": sorted(identities),
        "inference_performed": False,
    }


def prepare(repo, scan_id, config):
    cache = Cache(config.cache_dir)
    rows = repo.results(scan_id)
    photos = features_from_rows(rows, cache, verify=False)
    by_id = {p.id: p for p in photos}
    store = DuplicateStore(repo)
    detection = store.for_scan(scan_id) or {"groups": []}
    blocked, suppressed = store.corrections(photos)
    groups = []
    for group in detection["groups"]:
        members = [by_id[i] for i in group["members"] if i in by_id]
        if (
            len(members) != len(group["members"])
            or group_signature(members) != group["signature"]
            or group["signature"] in suppressed
            or any(a in group["members"] and b in group["members"] for a, b in blocked)
        ):
            continue
        groups.append(group)
    events = EventStore(repo).for_scan(scan_id, photos) or {"events": [], "assignments": {}}
    decisions = {
        str(r["photo_id"]): r["decision"] for r in repo.db.execute("SELECT * FROM user_decisions")
    }
    vectors, reuse = cached_vectors(repo, cache, photos, config.ranking.model)
    return {
        "photos": photos,
        "rows": {str(r["id"]): r for r in rows if str(r["id"]) in by_id},
        "groups": groups,
        "events": events,
        "decisions": decisions,
        "vectors": vectors,
        "embedding_reuse": reuse,
        "excluded_stale_or_incomplete": len(rows) - len(photos),
    }


def recommend(repo, config, data, members=None, context="event", k=20, scope="library"):
    started = time.perf_counter()
    ids = set(members) if members is not None else {p.id for p in data["photos"]}
    photos = [p for p in data["photos"] if p.id in ids]
    groups = [g for g in data["groups"] if set(g["members"]) & ids]
    assignments = data["events"]["assignments"]
    coverage = None
    if scope == "library":
        coverage = {p.id: assignments.get(p.id, {}).get("event_id") or "unassigned" for p in photos}
    vector_key = sorted(
        (p.id, hashlib.sha256(data["vectors"][p.id].tobytes()).hexdigest())
        for p in photos
        if p.id in data["vectors"]
    )
    analysis_id = repo.version(
        "PhotoRanking",
        VERSION,
        {
            "config": asdict(config.ranking),
            "numpy": np.__version__,
            "feature_policy": "complete-context cached vectors or hash fallback",
        },
    )
    key = parameter_hash(
        {
            "analysis": analysis_id,
            "context": context,
            "scope": scope,
            "k": k,
            "photos": sorted((p.id, p.fingerprint, p.source_versions) for p in photos),
            "groups": [(g["type"], g["signature"]) for g in groups],
            "coverage": coverage,
            "vectors": vector_key,
        }
    )
    cached = repo.db.execute(
        "SELECT result_json FROM ranking_results WHERE cache_key=?", (key,)
    ).fetchone()
    if cached:
        result = json.loads(cached[0])
    else:
        ranked = rank(photos, config.ranking, context, data["vectors"])
        selected = shortlist(
            photos, ranked["ranked"], k, config.ranking, data["vectors"], groups, coverage
        )
        result = {**ranked, **selected, "analysis_id": analysis_id, "scope": scope}
        with repo.db:
            repo.db.execute(
                "INSERT OR REPLACE INTO ranking_results VALUES (?,?,?)",
                (key, analysis_id, json.dumps(result, allow_nan=False)),
            )
    return {
        **result,
        "cache_hit": bool(cached),
        "total_seconds": time.perf_counter() - started,
        "embedding_reuse": data["embedding_reuse"],
    }


def recommendations_for_scan(repo, scan_id, config):
    data = prepare(repo, scan_id, config)
    result = recommend(repo, config, data)
    return {k: v for k, v in result.items() if k not in {"ranked", "selected"}}
