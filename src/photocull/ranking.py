"""Explainable contextual ranking and bounded greedy event coverage. No learning."""

import csv
import io
import json
import time
from bisect import bisect_right
from dataclasses import asdict

import numpy as np

from photocull.config import RankingConfig
from photocull.events import clock, normalize_vectors

VERSION = "ranking_v1.2"


def descriptors(photos, vectors=None):
    """Cache-only embeddings where complete; otherwise one consistent hash feature space."""
    vectors = normalize_vectors(vectors or {})
    if photos and all(p.id in vectors for p in photos):
        return np.array([vectors[p.id] for p in photos], dtype=np.float32), "cached_embedding"
    matrix = []
    for photo in photos:
        bits = int(photo.hashes.get("phash", "0"), 16)
        matrix.append([(1 if bits & (1 << i) else -1) / 8 for i in range(64)])
    return np.asarray(matrix, dtype=np.float32), "perceptual_hash_surrogate"


def clipped_quality(photo):
    value = float(photo.quality.get("technical_quality_v1", 0))
    if not np.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Invalid technical quality")
    return value


def rank(photos, config=None, context="event", vectors=None):
    config = config or RankingConfig()
    if context not in {"event", "burst", "duplicate"}:
        raise ValueError("Unknown ranking context")
    if len({p.id for p in photos}) != len(photos):
        raise ValueError("Ranking IDs must be unique")
    start = time.perf_counter()
    photos = sorted(photos, key=lambda p: p.id)
    if not photos:
        return {"ranked": [], "ranking_seconds": 0, "feature_source": "none", "comparisons": 0}
    matrix, feature_source = descriptors(photos, vectors)
    center = matrix.mean(axis=0)
    norm = np.linalg.norm(center)
    representation = (
        np.clip((matrix @ (center / norm) + 1) / 2, 0, 1)
        if norm > 1e-9
        else (np.full(len(photos), 0.5))
    )
    # Evenly sampled relevant peers bound work. Uniqueness never dominates relevance.
    pool = np.unique(
        np.linspace(0, len(photos) - 1, min(config.neighbor_limit + 1, len(photos)), dtype=int)
    )
    uniqueness = np.zeros(len(photos), dtype=np.float32)
    comparisons = 0
    for i in range(len(photos)):
        peers = pool[pool != i]
        if len(peers):
            uniqueness[i] = min(
                config.uniqueness_cap, max(0, 1 - float(np.max(matrix[peers] @ matrix[i])))
            )
            comparisons += len(peers)
    quality_values = [clipped_quality(p) for p in photos]
    sharpness_values = sorted(
        float(p.quality.get("normalized", {}).get("sharpness", clipped_quality(p))) for p in photos
    )
    output = []
    for i, photo in enumerate(photos):
        q, r = quality_values[i], float(representation[i])
        u = float(uniqueness[i]) if q >= config.quality_floor and r >= 0.35 else 0.0
        if config.variant == "A" or context == "duplicate":
            weights = (1.0, 0.0, 0.0)
        elif context == "burst":
            weights = (config.burst_quality_weight, 1 - config.burst_quality_weight, 0.0)
        else:
            weights = (
                config.quality_weight,
                config.representation_weight,
                config.uniqueness_weight,
            )
        score = weights[0] * q + weights[1] * r + weights[2] * u
        normalized = photo.quality.get("normalized", {})
        sharpness = float(normalized.get("sharpness", q))
        exposure = float(normalized.get("exposure", q))
        percentile = bisect_right(sharpness_values, sharpness) / len(photos)
        reasons = [
            f"Technical Quality v1: {q:.3f}",
            f"Sharpness percentile in this context: {percentile:.0%}",
            f"Exposure indicator: {exposure:.3f}",
            f"Resolution indicator: {normalized.get('resolution', q):.3f}",
            f"Noise proxy (not a scene classifier): "
            f"{photo.quality.get('raw', {}).get('noise_residual_mad', 0):.3f}",
        ]
        if weights[1]:
            reasons.append(f"Representation: {r:.3f} ({feature_source})")
        if weights[2]:
            reasons.append(f"Guarded uniqueness: {u:.3f}; capped at {config.uniqueness_cap:g}")
        weak = []
        if q < config.quality_floor:
            weak.append("Low technical score; uniqueness and coverage bonuses disabled")
        if sharpness < 0.2:
            weak.append("Low sharpness can be intentional blur")
        if exposure < 0.4:
            weak.append("Exposure proxy can penalize intentional low light")
        if r < 0.35:
            weak.append("Unusual local content; uniqueness contribution disabled")
        output.append(
            {
                "photo_id": photo.id,
                "score": score,
                "quality": q,
                "representation": r,
                "uniqueness": u,
                "weights": list(weights),
                "explanation": reasons,
                "weaker_points": weak,
                "sharpness": sharpness,
                "exposure": exposure,
                "resolution": float(normalized.get("resolution", q)),
                "clipping": sum(
                    float(photo.quality.get("raw", {}).get(k, 0))
                    for k in ("luminance_low_clipping", "luminance_high_clipping")
                ),
                "fingerprint": photo.fingerprint,
            }
        )
    output.sort(
        key=lambda r: (
            -r["score"],
            -r["sharpness"],
            -r["exposure"],
            -r["resolution"],
            r["clipping"],
            r["photo_id"],
        )
    )
    for index, row in enumerate(output, 1):
        row["raw_rank"] = index
    return {
        "ranked": output,
        "ranking_seconds": time.perf_counter() - start,
        "feature_source": feature_source,
        "comparisons": comparisons,
        "version": VERSION,
        "parameters": asdict(config),
        "context": context,
    }


def shortlist(photos, ranked, k=20, config=None, vectors=None, groups=(), coverage=None, safe=True):
    """Greedy MMR with soft temporal/event coverage and hard known-group suppression."""
    config = config or RankingConfig()
    if type(k) is not int or not 0 <= k <= 100:
        raise ValueError("Shortlist size must be an integer within 0..100")
    start = time.perf_counter()
    by_id = {p.id: p for p in photos}
    candidates = [dict(r) for r in ranked if r["photo_id"] in by_id]
    ordered = [by_id[r["photo_id"]] for r in candidates]
    matrix, source = descriptors(ordered, vectors)
    index = {p.id: i for i, p in enumerate(ordered)}
    memberships = {}
    for group_index, group in enumerate(groups):
        for identifier in group["members"]:
            memberships.setdefault(str(identifier), set()).add(group_index)
    if coverage is None:
        known = [clock(p)[0] for p in ordered if clock(p)[0] is not None]
        lo, hi = (min(known), max(known)) if known else (0, 0)
        coverage = {
            p.id: str(min(3, int(4 * (clock(p)[0] - lo) / (hi - lo + 1))))
            if clock(p)[0] is not None
            else "unknown"
            for p in ordered
        }
    selected, used_groups, used_bins = [], set(), set()
    excluded = []
    similarities = np.zeros(len(candidates), dtype=np.float32)
    comparisons = 0
    while candidates and len(selected) < k:
        choices = []
        for row in candidates:
            identifier = row["photo_id"]
            if safe and memberships.get(identifier, set()) & used_groups:
                excluded.append(
                    {"photo_id": identifier, "reason": "Known duplicate/burst suppressed"}
                )
                continue
            similarity = float(similarities[index[identifier]]) if selected else 0
            bonus = (
                config.coverage_bonus
                if config.variant == "B"
                and coverage.get(identifier) not in used_bins
                and row["quality"] >= config.quality_floor
                else 0
            )
            penalty = config.diversity_penalty * similarity if config.variant == "B" else 0
            choices.append((row["score"] - penalty + bonus, row, bonus))
        if not choices:
            break
        choices.sort(key=lambda c: (-c[0], c[1]["raw_rank"], c[1]["photo_id"]))
        adjusted, chosen, coverage_reward = choices[0]
        chosen = dict(chosen)
        identifier = chosen["photo_id"]
        chosen.update(
            {
                "rank": len(selected) + 1,
                "selection_score": adjusted,
                "coverage_region": coverage.get(identifier),
                "similarity_to_selected": float(similarities[index[identifier]]),
            }
        )
        chosen["explanation"] = chosen["explanation"] + [
            f"Diversity penalty: {config.diversity_penalty:g} × similarity "
            f"{chosen['similarity_to_selected']:.3f}"
            if config.variant == "B"
            else "Selected in technical-quality order",
            "Known duplicate/burst peers are suppressed"
            if safe
            else "Raw baseline without suppression",
            f"Coverage region: {coverage.get(identifier, 'unknown')}; "
            f"bonus applied: {coverage_reward:.3f}",
        ]
        selected.append(chosen)
        used_groups.update(memberships.get(identifier, set()))
        used_bins.add(coverage.get(identifier))
        candidates = [
            r
            for r in candidates
            if r["photo_id"] != identifier
            and not (safe and memberships.get(r["photo_id"], set()) & used_groups)
        ]
        similarities = np.maximum(similarities, np.clip(matrix @ matrix[index[identifier]], 0, 1))
        comparisons += len(ordered)
    return {
        "selected": selected,
        "shortlist_seconds": time.perf_counter() - start,
        "candidate_count": len(ranked),
        "selected_count": len(selected),
        "selection_comparisons": comparisons,
        "feature_source": source,
        "suppression": "at most one per known exact/near/burst group" if safe else "none",
        "shorter_than_requested": len(selected) < min(k, len(photos)),
    }


def export_manifest(selected, rows, events, decisions, format="json"):
    records = []
    for item in selected:
        identifier = item["photo_id"]
        source = rows[identifier]
        records.append(
            {
                "source_path": source["path"],
                "source_name": source["metadata"]["filename"],
                "rank": item["rank"],
                "event": events.get(identifier, "Unassigned"),
                "technical_quality_v1": item["quality"],
                "quality_metrics": {
                    "sharpness": item["sharpness"],
                    "exposure": item["exposure"],
                    "resolution": item["resolution"],
                    "clipping": item["clipping"],
                },
                "explanation": item["explanation"],
                "weaker_points": item["weaker_points"],
                "user_label": decisions.get(identifier, "unmarked"),
            }
        )
    if format == "json":
        return json.dumps(records, indent=2, allow_nan=False)
    if format != "csv":
        raise ValueError("Export format must be CSV or JSON")
    stream = io.StringIO()
    fields = (
        list(records[0])
        if records
        else [
            "source_path",
            "source_name",
            "rank",
            "event",
            "technical_quality_v1",
            "quality_metrics",
            "explanation",
            "weaker_points",
            "user_label",
        ]
    )
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for record in records:
        flattened = {
            k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
            for k, v in record.items()
        }
        # Spreadsheet formula injection guard; JSON keeps the exact original path/name.
        writer.writerow(
            {
                k: "'" + str(v) if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v
                for k, v in flattened.items()
            }
        )
    return stream.getvalue()
