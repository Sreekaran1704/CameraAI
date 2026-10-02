"""Versioned precision-first hybrid; Phase 2 comparator stays unchanged."""

from dataclasses import asdict

import numpy as np

from photocull.embeddings import cosine
from photocull.similarity import Relationship, SimilarityEngine, pair_key


def projection_neighbors(vectors, neighbors=16, probes=8):
    """Bounded sorted random projections: O(P*N*log N + P*N*K*D), no NxN matrix."""
    identifiers = sorted(vectors)
    if len(identifiers) < 2:
        return {}, {"retrieval_comparisons": 0}
    matrix = np.stack([vectors[i] for i in identifiers])
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    by_id = {identifier: i for i, identifier in enumerate(identifiers)}
    rng = np.random.default_rng(31704)
    projections = matrix @ rng.normal(size=(matrix.shape[1], probes)).astype(np.float32)
    candidates = {i: set() for i in identifiers}
    for probe in range(probes):
        order = np.argsort(projections[:, probe], kind="stable")
        for rank, index in enumerate(order):
            for other in order[max(0, rank - neighbors) : rank + neighbors + 1]:
                if other != index:
                    candidates[identifiers[index]].add(identifiers[other])
    pairs, count = set(), 0
    for identifier, choices in candidates.items():
        choices = sorted(choices)
        similarities = matrix[[by_id[i] for i in choices]] @ matrix[by_id[identifier]]
        ranked = [choices[i] for i in np.argsort(-similarities, kind="stable")]
        count += len(choices)
        for other in ranked[:neighbors]:
            pairs.add(pair_key(identifier, other))
    adjacency = {i: set() for i in identifiers}
    for a, b in pairs:
        adjacency[a].add(b)
        adjacency[b].add(a)
    return adjacency, {"retrieval_comparisons": count, "retrieval_pairs": len(pairs)}


class HybridEngine(SimilarityEngine):
    name = "HybridSimilarityEngine"
    version = "near_duplicate_v2"

    def __init__(self, config, embedding_config, vectors, identity):
        super().__init__(config)
        self.embedding_config, self.vectors, self.identity = embedding_config, vectors, identity
        self.extra_candidates, self.retrieval_stats = {}, {}
        self.candidate_radius = max(config.phash_distance, embedding_config.moderate_phash)

    @property
    def parameters(self):
        return {
            **super().parameters,
            "hybrid": asdict(self.embedding_config),
            "embedding_identity": self.identity,
            "reporting": "persistent-embedding-statistics-v1",
            "retrieval": "sorted-projections-seed31704-v1",
        }

    def compare(self, a, b):
        value = super().compare(a, b)
        e, c = value["evidence"], self.embedding_config
        similarity = (
            cosine(self.vectors[a.id], self.vectors[b.id])
            if a.id in self.vectors and b.id in self.vectors
            else None
        )
        e.update(
            {
                "embedding_cosine": similarity,
                "embedding_model": c.model,
                "embedding_identity": self.identity,
                "embedding_changed_classification": False,
            }
        )
        trusted_time = e["timestamp_reliability"] in {"exif_naive", "exif_timezone"}
        recovered = (
            c.recovery_enabled
            and not value["near"]
            and self.textured(a)
            and self.textured(b)
            and similarity is not None
            and similarity >= c.cosine_threshold
            and e["phash"] <= c.moderate_phash
            and e["dhash"] <= c.corroborating_hash
            and e["ahash"] <= c.corroborating_hash
            and e["aspect_log_difference"] <= c.aspect_limit
            and e["verification_correlation"] is not None
            and e["verification_correlation"] >= c.pixel_floor
            and e["chroma_difference"] <= self.config.chroma_difference
            and (not trusted_time or e["capture_gap_seconds"] == 0)
        )
        if recovered:
            value.update(
                {
                    "near": True,
                    "relationship": str(Relationship.NEAR_DUPLICATE),
                    "heuristic_reliability": 0.85,
                    "reason": "Strong local embedding agreement plus moderate hashes, "
                    "pixel/aspect/color and capture-time guards recovered the pair.",
                }
            )
            e["embedding_changed_classification"] = True
        return value

    def detect(self, *args, **kwargs):
        c = self.embedding_config
        self.extra_candidates, self.retrieval_stats = projection_neighbors(
            self.vectors, c.retrieval_neighbors, c.retrieval_probes
        )
        result = super().detect(*args, **kwargs)
        result["statistics"].update(self.retrieval_stats)
        return result
