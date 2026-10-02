from dataclasses import replace

import numpy as np
import pytest

from photocull.config import DuplicateConfig
from photocull.similarity import (
    BKTree,
    PhotoFeatures,
    Relationship,
    SimilarityEngine,
    temporal_evidence,
    verification_from_image,
)


def feature(identifier, phash=0, score=0.8, **kwargs):
    vector = np.ones(1024, dtype=np.float32) / 32
    return PhotoFeatures(
        id=str(identifier),
        fingerprint=f"fp-{identifier}",
        sha256=kwargs.pop("sha256", None),
        width=256,
        height=256,
        size=8000,
        hashes={"phash": f"{phash:016x}", "dhash": "0" * 16, "ahash": "0" * 16},
        quality={
            "raw": {"entropy_bits": 6, "contrast_p95_p5": 150},
            "normalized": {"sharpness": score, "exposure": score, "resolution": 0.5},
            "technical_quality_v1": score,
        },
        verification=(vector, np.zeros(3)),
        **kwargs,
    )


def test_exact_three_copies_and_savings():
    photos = [feature(i, sha256="equal") for i in range(3)]
    result = SimilarityEngine(DuplicateConfig()).detect(photos)
    exact = result["groups"][0]
    assert exact["type"] == Relationship.EXACT_DUPLICATE
    assert len(exact["members"]) == 3 and len(result["pairs"]) == 2
    assert result["exact_reclaimable_bytes"] == 16000
    assert result["near_candidate_bytes"] == 0


def test_exact_missing_hash_not_equal():
    result = SimilarityEngine(DuplicateConfig()).detect([feature(1), feature(2)])
    assert not any(g["type"] == Relationship.EXACT_DUPLICATE for g in result["groups"])


def test_hash_corroboration():
    engine = SimilarityEngine(DuplicateConfig())
    a, b = feature(1), feature(2, phash=3)
    assert engine.compare(a, b)["near"]
    b.hashes["dhash"] = "f" * 16
    assert not engine.compare(a, b)["near"]
    assert engine.compare(a, b)["evidence"]["dhash"] == 64


def test_low_texture_collision_guard():
    engine = SimilarityEngine(DuplicateConfig())
    a, b = feature(1), feature(2)
    b.quality["raw"]["entropy_bits"] = 0.5
    assert not engine.compare(a, b)["near"]
    assert engine.detect([a, b])["statistics"]["low_texture_excluded"] == 1
    a.sha256 = b.sha256 = "same"
    assert engine.compare(a, b)["relationship"] == Relationship.EXACT_DUPLICATE


def test_pixel_verification_rejects_unrelated():
    a, b = feature(1), feature(2)
    b.verification = (-b.verification[0], b.verification[1])
    assert not SimilarityEngine(DuplicateConfig()).compare(a, b)["near"]
    assert SimilarityEngine(DuplicateConfig()).compare(a, b)["evidence"]["phash"] == 0


def test_aspect_and_chroma_guards():
    a, b = feature(1), feature(2)
    b.width = 100
    assert not SimilarityEngine(DuplicateConfig()).compare(a, b)["near"]
    b.width = 256
    b.verification = (b.verification[0], np.ones(3))
    assert not SimilarityEngine(DuplicateConfig()).compare(a, b)["near"]


def test_complete_link_prevents_chain():
    a, b, c = feature("a", 0), feature("b", 1), feature("c", 3)
    engine = SimilarityEngine(DuplicateConfig(phash_distance=1))
    assert engine.compare(a, b)["near"] and engine.compare(b, c)["near"]
    assert not engine.compare(a, c)["near"]
    result = engine.detect([a, b, c])
    assert result["groups"][0]["members"] == ["a", "b"]
    assert result["groups"][0]["max_phash_distance"] == 1
    assert all(set(g["members"]) != {"a", "b", "c"} for g in result["groups"])


def test_temporal_hierarchy_and_offsets():
    a = feature(1, capture_time="2026-01-01T12:00:00", capture_timezone="-06:00")
    b = feature(2, capture_time="2026-01-01T18:00:02", capture_timezone="+00:00")
    assert temporal_evidence(a, b) == (2, "exif_timezone")
    b.capture_timezone = None
    assert temporal_evidence(a, b) == (None, "incomparable")
    a.capture_timezone = None
    assert temporal_evidence(a, b) == (21602, "exif_naive")
    a.capture_time = b.capture_time = None
    a.filesystem_time = "2026-01-01T00:00:00+00:00"
    b.filesystem_time = "2026-01-01T00:00:02+00:00"
    assert temporal_evidence(a, b) == (2, "filesystem")
    assert not SimilarityEngine(DuplicateConfig()).compare(a, b)["burst"]
    assert SimilarityEngine(DuplicateConfig(allow_filesystem_bursts=True)).compare(a, b)["burst"]


def test_burst_and_maximum_span():
    photos = [
        feature(str(i), capture_time=f"2026-01-01T12:00:0{s}", capture_timezone="+00:00")
        for i, s in enumerate((0, 3, 7))
    ]
    engine = SimilarityEngine(DuplicateConfig())
    assert engine.compare(photos[0], photos[1])["burst"]
    assert not engine.compare(photos[0], photos[2])["burst"]
    bursts = [g for g in engine.detect(photos)["groups"] if g["type"] == Relationship.BURST_GROUP]
    assert bursts[0]["members"] == ["0", "1"]
    assert not any(len(g["members"]) == 3 for g in bursts)


def test_far_capture_not_near():
    a = feature(1, capture_time="2026-01-01T00:00:00", capture_timezone="+00:00")
    b = feature(2, capture_time="2026-07-01T00:00:00", capture_timezone="+00:00")
    assert not SimilarityEngine(DuplicateConfig()).compare(a, b)["near"]


def test_representative_and_disjoint_savings():
    a = feature("a", score=0.7, sha256="exact")
    b = feature("b", score=0.7, sha256="exact")
    c = feature("c", score=0.9, sha256="other")
    result = SimilarityEngine(DuplicateConfig()).detect([a, b, c])
    assert result["exact_reclaimable_bytes"] == 8000
    assert result["near_candidate_bytes"] == 8000
    near = next(g for g in result["groups"] if g["type"] == Relationship.NEAR_DUPLICATE)
    assert near["representative"] == "c"
    assert "Highest Technical Quality" in near["representative_reason"]


def test_hardlink_savings_excluded():
    photos = [feature(i, sha256="same", link_count=2) for i in range(2)]
    assert SimilarityEngine(DuplicateConfig()).detect(photos)["exact_reclaimable_bytes"] == 0


def test_bktree_matches_brute_force():
    from photocull.hashing import hamming

    tree = BKTree()
    values = [f"{i * 1234567:016x}" for i in range(30)]
    for i, value in enumerate(values):
        tree.add(value, str(i))
    for value in values:
        assert set(tree.query(value, 8)) == {
            str(i) for i, candidate in enumerate(values) if hamming(value, candidate) <= 8
        }


def test_budget_limits_are_visible_and_conservative():
    result = SimilarityEngine(DuplicateConfig(max_comparisons=2)).detect(
        [feature(i) for i in range(8)]
    )
    assert result["statistics"]["budget_limited"]
    assert result["statistics"]["expensive_comparisons"] <= 2
    assert max(len(g["members"]) for g in result["groups"]) <= 2


def test_engine_cancellation():
    with pytest.raises(InterruptedError):
        SimilarityEngine(DuplicateConfig()).detect([feature(1)], cancelled=lambda: True)


def test_in_memory_transforms_and_crop_measurements():
    from PIL import ImageEnhance

    from photocull.config import QualityConfig
    from photocull.duplicate_evaluation import scene
    from photocull.hashing import PerceptualHashService
    from photocull.quality import QualityAnalyzer

    image = scene(17)
    service = PerceptualHashService()
    qa = QualityAnalyzer(QualityConfig())
    a = feature("a")
    a.hashes, a.quality, a.verification = (
        service.analyze(image),
        qa.analyze(image),
        verification_from_image(image),
    )
    engine = SimilarityEngine(DuplicateConfig(phash_distance=12))
    for variant in (image.resize((384, 384)), ImageEnhance.Brightness(image).enhance(1.10)):
        b = replace(
            a,
            id="b",
            fingerprint="b",
            hashes=service.analyze(variant),
            verification=verification_from_image(variant),
        )
        assert engine.compare(a, b)["near"]
    crop = image.crop((40, 40, 200, 200))
    b = replace(a, id="c", hashes=service.analyze(crop), verification=verification_from_image(crop))
    assert not engine.compare(a, b)["near"]
