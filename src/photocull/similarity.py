"""Read-only, path-independent conservative similarity and complete-link grouping."""

import math
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum

import numpy as np
from PIL import Image

from photocull.config import DuplicateConfig, parameter_hash
from photocull.hashing import hamming
from photocull.provenance import image_runtime


class Relationship(StrEnum):
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    NEAR_DUPLICATE = "NEAR_DUPLICATE"
    BURST_GROUP = "BURST_GROUP"
    VISUALLY_SIMILAR = "VISUALLY_SIMILAR"  # Reserved; no semantic classification.


@dataclass
class PhotoFeatures:
    id: str
    fingerprint: str
    sha256: str | None
    width: int
    height: int
    size: int
    hashes: dict
    quality: dict
    capture_time: str | None = None
    capture_timezone: str | None = None
    filesystem_time: str | None = None
    filename: str = ""
    source_versions: dict = field(default_factory=dict)
    verification: tuple | None = field(default=None, repr=False)
    storage_identity: str | None = None
    link_count: int = 1


def verification_from_image(image: Image.Image):
    """Temporary normalized pixels for deterministic verification, no learned encoder/cache."""
    rgb = (
        np.asarray(
            image.convert("RGB").resize((32, 32), Image.Resampling.LANCZOS), dtype=np.float32
        )
        / 255
    )
    gray = np.asarray(
        image.convert("L").resize((32, 32), Image.Resampling.LANCZOS), dtype=np.float32
    )
    centered = gray.ravel() - gray.mean()
    norm = float(np.linalg.norm(centered))
    normalized = centered / norm if norm > 1e-6 else np.zeros(1024, dtype=np.float32)
    mean = rgb.mean(axis=(0, 1))
    chroma = mean - mean.mean()
    return normalized, chroma


def timestamp(photo: PhotoFeatures):
    if photo.capture_time:
        try:
            value = datetime.fromisoformat(photo.capture_time)
            if photo.capture_timezone and value.tzinfo is None:
                value = datetime.fromisoformat(photo.capture_time + photo.capture_timezone)
            return value, "exif_timezone" if value.tzinfo else "exif_naive"
        except ValueError:
            pass
    if photo.filesystem_time:
        try:
            return datetime.fromisoformat(photo.filesystem_time), "filesystem"
        except ValueError:
            pass
    return None, "unknown"


def temporal_evidence(a, b):
    left, left_kind = timestamp(a)
    right, right_kind = timestamp(b)
    if left is None or right is None or left_kind != right_kind:
        return None, "incomparable"
    if bool(left.tzinfo) != bool(right.tzinfo):
        return None, "incomparable"
    return abs((left - right).total_seconds()), left_kind


def pair_key(a, b):
    return tuple(sorted((str(a), str(b))))


def group_signature(members):
    return parameter_hash({"members": sorted((p.id, p.fingerprint) for p in members)})


class BKTree:
    """Metric index over unique pHash values; query radius has no prefix-boundary misses."""

    def __init__(self):
        self.root = None

    def add(self, value, identifier):
        if self.root is None:
            self.root = [value, [identifier], {}]
            return
        node = self.root
        while True:
            distance = hamming(value, node[0])
            if distance == 0:
                node[1].append(identifier)
                return
            if distance not in node[2]:
                node[2][distance] = [value, [identifier], {}]
                return
            node = node[2][distance]

    def query(self, value, radius):
        if self.root is None:
            return
        stack = [self.root]
        while stack:
            node = stack.pop()
            distance = hamming(value, node[0])
            if distance <= radius:
                yield from node[1]
            stack.extend(
                child
                for edge, child in node[2].items()
                if distance - radius <= edge <= distance + radius
            )


class SimilarityEngine:
    name = "SimilarityEngine"
    version = "duplicates_v1"

    def __init__(self, config: DuplicateConfig):
        self.config = config

    @property
    def parameters(self):
        return {
            **asdict(self.config),
            "runtime": image_runtime(),
            "verification": "thumbnail-gray32-correlation-chroma-v1",
            "grouping": "deterministic-complete-link-v1",
            "representative": "quality-resolution-sharpness-exposure-v1",
        }

    def textured(self, photo):
        raw = photo.quality["raw"]
        return (
            raw["entropy_bits"] >= self.config.min_entropy
            and raw["contrast_p95_p5"] >= self.config.min_contrast
        )

    def compare(self, a: PhotoFeatures, b: PhotoFeatures):
        c = self.config
        distances = {
            name: hamming(a.hashes[name], b.hashes[name]) for name in ("phash", "dhash", "ahash")
        }
        gap, reliability = temporal_evidence(a, b)
        aspect = abs(math.log((a.width / a.height) / (b.width / b.height)))
        dimension_ratio = min(a.width * a.height, b.width * b.height) / max(
            a.width * a.height, b.width * b.height
        )
        correlation, chroma = None, None
        if a.verification is not None and b.verification is not None:
            correlation = float(np.clip(np.dot(a.verification[0], b.verification[0]), -1, 1))
            chroma = float(np.max(np.abs(a.verification[1] - b.verification[1])))
        sequence_a = re.search(r"(\d+)(?=\.[^.]+$)", a.filename)
        sequence_b = re.search(r"(\d+)(?=\.[^.]+$)", b.filename)
        sequence_gap = (
            abs(int(sequence_a[1]) - int(sequence_b[1])) if sequence_a and sequence_b else None
        )
        evidence = {
            **distances,
            "aspect_log_difference": aspect,
            "dimension_area_ratio": dimension_ratio,
            "dimensions": [[a.width, a.height], [b.width, b.height]],
            "capture_gap_seconds": gap,
            "timestamp_reliability": reliability,
            "verification_correlation": correlation,
            "chroma_difference": chroma,
            "filename_sequence_gap": sequence_gap,
        }
        warnings = ["Reliability scores are heuristic, not calibrated probabilities."]
        if correlation is None:
            warnings.append("Local pixel verification unavailable; perceptual matches disabled.")
        if reliability != "exif_timezone":
            warnings.append("Capture time lacks comparable timezone-aware EXIF evidence.")
        exact = bool(a.sha256 and a.sha256 == b.sha256)
        textured = self.textured(a) and self.textured(b)
        trusted_time = reliability in {"exif_timezone", "exif_naive"}
        near = (
            not exact
            and textured
            and distances["phash"] <= c.phash_distance
            and distances["dhash"] <= c.dhash_distance
            and distances["ahash"] <= c.ahash_distance
            and aspect <= c.aspect_log_difference
            and correlation is not None
            and correlation >= c.verification_correlation
            and chroma <= c.chroma_difference
            and (not trusted_time or gap <= c.near_capture_window)
        )
        burst = (
            not exact
            and textured
            and gap is not None
            and gap <= c.burst_window
            and (trusted_time or c.allow_filesystem_bursts and reliability == "filesystem")
            and distances["phash"] <= c.burst_phash_distance
            and distances["dhash"] <= c.burst_dhash_distance
            and distances["ahash"] <= c.burst_ahash_distance
            and aspect <= c.burst_aspect_log_difference
            and correlation is not None
            and correlation >= c.burst_correlation
            and chroma <= c.chroma_difference
        )
        kind = (
            Relationship.EXACT_DUPLICATE
            if exact
            else Relationship.NEAR_DUPLICATE
            if near
            else Relationship.BURST_GROUP
            if burst
            else None
        )
        reason = (
            "Identical file SHA-256."
            if exact
            else "Strong pHash agreement, corroborating hashes and local pixel verification."
            if near
            else "Short capture interval with perceptual agreement; poses may differ."
            if burst
            else "Insufficient evidence for duplication or a burst."
        )
        if not textured and not exact:
            warnings.append("Low-texture/low-contrast hash collision guard rejected this pair.")
        if gap is not None and trusted_time and gap > c.near_capture_window:
            warnings.append(
                "Reliable capture times are too far apart for near-duplicate inference."
            )
        return {
            "relationship": str(kind) if kind else None,
            "near": near or exact,
            "burst": burst,
            "heuristic_reliability": 1.0
            if exact
            else 0.9
            if near
            else 0.8
            if burst and reliability == "exif_timezone"
            else 0.6
            if burst
            else 0.0,
            "evidence": evidence,
            "reason": reason,
            "warnings": warnings,
        }

    def representative(self, members):
        def score(photo):
            q = photo.quality
            return (
                -q["technical_quality_v1"],
                -photo.width * photo.height,
                -q["normalized"]["sharpness"],
                -q["normalized"]["exposure"],
                photo.id,
            )

        chosen = min(members, key=score)
        alternatives = [p for p in members if p.id != chosen.id]
        sharper = sum(
            chosen.quality["normalized"]["sharpness"] > p.quality["normalized"]["sharpness"]
            for p in alternatives
        )
        exposed = sum(
            chosen.quality["normalized"]["exposure"] > p.quality["normalized"]["exposure"]
            for p in alternatives
        )
        reason = (
            "Highest Technical Quality v1; resolution, sharpness and exposure break ties. "
            f"Sharper than {sharper} alternative(s); higher exposure indicator than "
            f"{exposed}. Artistic preference may differ."
        )
        return chosen, reason

    def detect(
        self, photos: list[PhotoFeatures], blocked=None, suppressed=None, cancelled=lambda: False
    ):
        blocked = blocked or set()
        suppressed = suppressed or set()
        c = self.config
        photos = sorted(photos, key=lambda p: p.id)
        by_id = {p.id: p for p in photos}
        if len(by_id) != len(photos):
            raise ValueError("Photo feature IDs must be unique")
        statistics = {
            "candidate_pairs": 0,
            "expensive_comparisons": 0,
            "budget_limited": False,
            "low_texture_excluded": 0,
            "exact_copies_collapsed": 0,
        }
        groups, pairs, cache = [], [], {}

        def group(kind, members, evidence):
            if len(members) < 2 or group_signature(members) in suppressed:
                return
            rep, reason = self.representative(members)
            max_distance = max((e["evidence"]["phash"] for e in evidence), default=0)
            groups.append(
                {
                    "type": str(kind),
                    "members": [p.id for p in members],
                    "representative": rep.id,
                    "representative_reason": reason,
                    "max_phash_distance": max_distance,
                    "signature": group_signature(members),
                    "evidence": evidence,
                    "reason": "SHA-256 equality"
                    if kind == Relationship.EXACT_DUPLICATE
                    else "Every member pair satisfies the configured rule (complete link).",
                }
            )

        # Exact content buckets require O(N) hashing, and compact star evidence, not all pairs.
        buckets = defaultdict(list)
        for p in photos:
            buckets[p.sha256 or f"missing:{p.id}"].append(p)
        canonical = []
        for members in buckets.values():
            partitions = [members] if not blocked else []
            if not blocked:
                remaining = []
            else:
                remaining = members
            for photo in remaining:
                for partition in partitions:
                    if not any(pair_key(photo.id, other.id) in blocked for other in partition):
                        partition.append(photo)
                        break
                else:
                    partitions.append([photo])
            for partition in partitions:
                rep, _ = self.representative(partition)
                canonical.append(rep)
                statistics["exact_copies_collapsed"] += len(partition) - 1
                evidence = [
                    {"a": rep.id, "b": p.id, **self.compare(rep, p)}
                    for p in partition
                    if p.id != rep.id
                ]
                group(Relationship.EXACT_DUPLICATE, partition, evidence)
                pairs.extend(evidence)
        tree = BKTree()
        textured = [p for p in sorted(canonical, key=lambda p: p.id) if self.textured(p)]
        statistics["low_texture_excluded"] = len(canonical) - len(textured)
        eligible_ids = {p.id for p in textured}
        adjacency = {"near": defaultdict(set), "burst": defaultdict(set)}

        def compare(a, b):
            key = pair_key(a.id, b.id)
            if key in blocked:
                return None
            if key in cache:
                return cache[key]
            if statistics["expensive_comparisons"] >= c.max_comparisons:
                statistics["budget_limited"] = True
                return None
            value = {"a": key[0], "b": key[1], **self.compare(by_id[key[0]], by_id[key[1]])}
            statistics["expensive_comparisons"] += 1
            cache[key] = value
            return value

        for photo in textured:
            if cancelled():
                raise InterruptedError("Duplicate detection cancelled")
            near_radius = getattr(self, "candidate_radius", c.phash_distance)
            radius = max(near_radius, c.burst_phash_distance)
            identifiers = tree.query(photo.hashes["phash"], radius)
            if hasattr(self, "extra_candidates"):
                identifiers = sorted(
                    set(identifiers)
                    | {
                        i
                        for i in self.extra_candidates.get(photo.id, ())
                        if i < photo.id and i in eligible_ids
                    }
                )
            for i, identifier in enumerate(identifiers):
                if i >= c.max_candidates_per_photo:
                    statistics["budget_limited"] = True
                    break
                statistics["candidate_pairs"] += 1
                if photo.sha256 and photo.sha256 == by_id[identifier].sha256:
                    continue
                candidate = by_id[identifier]
                distance = hamming(photo.hashes["phash"], candidate.hashes["phash"])
                gap, reliability = temporal_evidence(photo, candidate)
                if distance > near_radius and (
                    gap is None
                    or gap > c.burst_window
                    or reliability == "filesystem"
                    and not c.allow_filesystem_bursts
                ):
                    continue
                evidence = compare(photo, by_id[identifier])
                if evidence:
                    for key in adjacency:
                        if evidence[key]:
                            adjacency[key][photo.id].add(identifier)
                            adjacency[key][identifier].add(photo.id)
            tree.add(photo.hashes["phash"], photo.id)

        # Greedy deterministic complete-link partition; no connected-component chaining.
        for flag, kind in (
            ("near", Relationship.NEAR_DUPLICATE),
            ("burst", Relationship.BURST_GROUP),
        ):
            assigned = set()
            for photo in textured:
                if photo.id in assigned:
                    continue
                members = [photo]
                evidence = []
                for identifier in sorted(adjacency[flag][photo.id]):
                    if identifier in assigned:
                        continue
                    if len(members) >= c.max_group_members:
                        statistics["budget_limited"] = True
                        continue
                    candidate = by_id[identifier]
                    values = [compare(candidate, p) for p in members]
                    if all(v is not None and v[flag] for v in values):
                        members.append(candidate)
                        evidence.extend(values)
                if len(members) > 1:
                    assigned.update(p.id for p in members)
                    group(kind, members, evidence)
        pairs.extend(v for v in cache.values() if v["relationship"] is not None)
        # Exact and near groups are disjoint for savings: near works on one retained file per SHA.
        exact_bytes = near_bytes = 0
        for g in groups:
            amount = sum(
                by_id[i].size
                for i in g["members"]
                if i != g["representative"] and by_id[i].link_count == 1
            )
            if g["type"] == Relationship.EXACT_DUPLICATE:
                exact_bytes += amount
            elif g["type"] == Relationship.NEAR_DUPLICATE:
                near_bytes += amount
        return {
            "groups": groups,
            "pairs": pairs,
            "statistics": statistics,
            "exact_reclaimable_bytes": exact_bytes,
            "near_candidate_bytes": near_bytes,
        }
