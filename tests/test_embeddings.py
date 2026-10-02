"""Offline contracts; fixture backends never fetch model weights."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from photocull.cache import Cache
from photocull.config import Config, DuplicateConfig, EmbeddingConfig
from photocull.duplicate_evaluation import load_manifest, score_split
from photocull.embeddings import (
    EmbeddingService,
    ModelUnavailable,
    cosine,
    file_checksum,
    normalize,
    preprocess,
    select_device,
)
from photocull.hybrid import HybridEngine, projection_neighbors
from photocull.pipeline import run_sync
from photocull.similarity import PhotoFeatures, SimilarityEngine
from photocull.storage import Repository


def fake_service(tmp_path, backend=None):
    cache = Cache(tmp_path / "cache")
    path = cache.root / "models" / "mobilenet.pt"
    path.write_bytes(b"fake safe fixture weights")
    path.with_suffix(".json").write_text(json.dumps({"sha256": file_checksum(path)}))
    calls = []

    def encode(batch):
        calls.append(len(batch))
        result = np.ones((len(batch), 576), dtype=np.float32)
        result[:, 0] = batch.mean(axis=(1, 2, 3))
        return result

    return EmbeddingService(cache, "mobilenet", backend=backend or encode, batch_size=2), calls


def test_normalization_cosine():
    vectors = normalize([[3, 4], [4, 3]])
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1)
    assert cosine([1, 0], [0, 1]) == 0
    assert cosine([1, 1], [2, 2]) == pytest.approx(1)
    with pytest.raises(ValueError):
        normalize([0, 0])
    with pytest.raises(ValueError):
        normalize([float("nan"), 1])


@pytest.mark.parametrize("model", ["mobilenet", "tinyclip"])
def test_preprocessing(model):
    image = Image.new("RGB", (315, 220), (120, 40, 70))
    a, b = preprocess(image, model), preprocess(image, model)
    np.testing.assert_array_equal(a, b)
    assert a.shape == (3, 224, 224) and a.dtype == np.float32


def test_batch_cache_and_invalidation(tmp_path):
    service, calls = fake_service(tmp_path)
    records = [
        (str(i), f"fp-{i}", lambda: Image.new("RGB", (64, 80), (70, 30, 100))) for i in range(5)
    ]
    first, stats = service.encode(records)
    assert calls == [2, 2, 1] and stats["generated"] == 5
    second, stats = service.encode(records)
    assert stats["cache_hits"] == 5 and calls == [2, 2, 1]
    np.testing.assert_array_equal(first["0"], second["0"])
    service.identity["preprocessing"] = "test-v2"
    assert service.encode(records)[1]["generated"] == 5
    service.identity["service_version"] = "test-v2"
    assert service.encode(records)[1]["generated"] == 5
    changed = list(records)
    changed[0] = ("0", "changed", records[0][2])
    assert service.encode(changed)[1]["generated"] == 1


def test_weight_checksum_and_reinstall(tmp_path):
    service, _ = fake_service(tmp_path)
    records = [("p", "fp", lambda: Image.new("RGB", (32, 32), "red"))]
    service.encode(records)
    service.path.write_bytes(b"changed")
    with pytest.raises(ModelUnavailable, match="checksum"):
        EmbeddingService(service.cache, "mobilenet", backend=lambda x: x)
    service.path.with_suffix(".json").write_text(
        json.dumps({"sha256": file_checksum(service.path)})
    )
    newer = EmbeddingService(service.cache, "mobilenet", backend=lambda x: np.ones((len(x), 576)))
    assert newer.encode(records)[1]["generated"] == 1


def test_corrupt_cache_regenerates(tmp_path):
    service, _ = fake_service(tmp_path)
    records = [("p", "fp", lambda: Image.new("RGB", (32, 32), "blue"))]
    service.encode(records)
    next((service.cache.root / "embeddings").glob("*.npy")).write_bytes(b"broken")
    assert service.encode(records)[1]["generated"] == 1


def test_device_cpu_fallback():
    torch = SimpleNamespace(
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False))
    )
    assert select_device(torch, "auto") == select_device(torch, "mps") == "cpu"


def test_missing_model_hash_fallback(config, photos):
    config = replace(config, embeddings=EmbeddingConfig(model="mobilenet"))
    result = run_sync(photos, config)
    assert not result["duplicates"]["embeddings"]["enabled"]
    assert result["duplicates"]["embeddings"]["fallback"] == "hash-only"
    assert "model-setup" in result["duplicates"]["embeddings"]["warning"]


def test_config_backwards_compatible():
    config = Config()
    snapshot = config.snapshot()
    snapshot.pop("embeddings")
    assert Config.from_snapshot(snapshot).embeddings.model == "disabled"
    with pytest.raises(ValueError):
        EmbeddingConfig(cosine_threshold=float("nan"))


def feature(identifier, phash):
    return PhotoFeatures(
        identifier,
        identifier,
        identifier,
        256,
        256,
        100,
        {"phash": phash, "dhash": "0" * 16, "ahash": "0" * 16},
        {
            "raw": {"entropy_bits": 6, "contrast_p95_p5": 100},
            "normalized": {"sharpness": 0.5, "exposure": 0.5},
            "technical_quality_v1": 0.5,
        },
        verification=(np.array([1.0, 0.0]), np.zeros(3)),
    )


def test_hybrid_corroboration_and_recovery():
    a, b = feature("a", "0" * 16), feature("b", "000000000000001f")
    vectors = {"a": np.array([1.0, 0.0]), "b": np.array([1.0, 0.0])}
    baseline = SimilarityEngine(DuplicateConfig())
    engine = HybridEngine(DuplicateConfig(), EmbeddingConfig(model="mobilenet"), vectors, {})
    assert not baseline.compare(a, b)["near"]
    assert engine.compare(a, b)["near"]
    assert engine.compare(a, b)["evidence"]["embedding_changed_classification"]
    assert len(engine.detect([a, b])["groups"]) == 1
    b.hashes["phash"] = "f" * 16
    assert not engine.compare(a, b)["near"]
    b.hashes["phash"] = "000000000000001f"
    b.verification = (np.array([0.0, 1.0]), np.zeros(3))
    assert not engine.compare(a, b)["near"]


def test_semantic_same_subject_far_date_negative():
    a, b = feature("a", "0" * 16), feature("b", "000000000000001f")
    a.capture_time, b.capture_time = "2026-01-01T12:00:00", "2026-04-01T12:00:00"
    engine = HybridEngine(
        DuplicateConfig(),
        EmbeddingConfig(model="tinyclip"),
        {"a": np.array([1.0, 0.0]), "b": np.array([1.0, 0.0])},
        {},
    )
    assert not engine.compare(a, b)["near"]


def test_projection_index_bounded_deterministic():
    vectors = {str(i): normalize(np.random.default_rng(i).normal(size=64)) for i in range(100)}
    a, stats = projection_neighbors(vectors, 4, 3)
    assert a == projection_neighbors(vectors, 4, 3)[0]
    assert stats["retrieval_comparisons"] <= 100 * 8 * 3
    assert all(i not in choices for i, choices in a.items())


def test_embedding_migration_clear_keeps_weights(tmp_path):
    service, _ = fake_service(tmp_path)
    repo = Repository(service.cache.root / "metadata.db")
    assert repo.db.execute("PRAGMA user_version").fetchone()[0] == 6
    service.encode([("p", "fp", lambda: Image.new("RGB", (32, 32), "red"))])
    service.cache.clear_derived(repo)
    assert service.path.is_file()
    assert not list((service.cache.root / "embeddings").iterdir())
    repo.close()


def test_frozen_phase2_benchmark(tmp_path):
    path = Path(__file__).parents[1] / "benchmark-output/phase2-v1/manifest.json"
    if not path.exists():
        from photocull.duplicate_evaluation import generate_duplicate_dataset

        generate_duplicate_dataset(tmp_path)
        path = tmp_path / "manifest.json"
    manifest, records = load_manifest(path)
    scored = score_split(
        SimilarityEngine(DuplicateConfig()),
        [p for split, p in records if split == "held_out"],
        [p for p in manifest["pairs"] if p["split"] == "held_out"],
    )
    metrics = scored["metrics"]["near"]
    assert (metrics["tp"], metrics["fp"], metrics["fn"], metrics["tn"]) == (60, 1, 24, 66)


def test_hybrid_exact_copies_are_not_counted_twice():
    a, copy, edited = (
        feature("a", "0" * 16),
        feature("copy", "0" * 16),
        feature("edited", "000000000000001f"),
    )
    copy.sha256 = a.sha256
    engine = HybridEngine(
        DuplicateConfig(),
        EmbeddingConfig(model="mobilenet"),
        {p.id: np.array([1.0, 0.0]) for p in (a, copy, edited)},
        {},
    )
    result = engine.detect([a, copy, edited])
    near = [g for g in result["groups"] if g["type"] == "NEAR_DUPLICATE"]
    assert len(near) == 1 and len(near[0]["members"]) == 2
    assert result["exact_reclaimable_bytes"] == result["near_candidate_bytes"] == 100


def test_malformed_model_manifest_is_unavailable(tmp_path):
    service, _ = fake_service(tmp_path)
    service.path.with_suffix(".json").write_text("{broken")
    with pytest.raises(ModelUnavailable, match="manifest"):
        EmbeddingService(service.cache, "mobilenet", backend=lambda x: x)


def test_hybrid_distinct_capture_frames_remain_bursts():
    a, b = feature("a", "0" * 16), feature("b", "000000000000001f")
    a.capture_time, b.capture_time = "2026-01-01T12:00:00", "2026-01-01T12:00:03"
    engine = HybridEngine(
        DuplicateConfig(),
        EmbeddingConfig(model="mobilenet"),
        {"a": np.array([1.0, 0.0]), "b": np.array([1.0, 0.0])},
        {},
    )
    value = engine.compare(a, b)
    assert not value["near"] and value["burst"]


def test_pipeline_embedding_provenance_persists_and_reuses(config, photos, monkeypatch):
    import photocull.embeddings as module
    from photocull.duplicate_storage import DuplicateStore

    cache = Cache(config.cache_dir)
    path = cache.root / "models" / "mobilenet.pt"
    path.write_bytes(b"offline fixture model")
    path.with_suffix(".json").write_text(json.dumps({"sha256": file_checksum(path)}))
    original = module.EmbeddingService

    def fixture_service(*args, **kwargs):
        kwargs["backend"] = lambda batch: np.ones((len(batch), 576), dtype=np.float32)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "EmbeddingService", fixture_service)
    config = replace(config, embeddings=EmbeddingConfig(model="mobilenet"))
    cold = run_sync(photos, config)
    repo = Repository(cache.root / "metadata.db")
    stored = DuplicateStore(repo).for_scan(cold["run_id"])
    assert stored["embeddings"]["enabled"]
    assert stored["embeddings"]["generated"] == stored["eligible_photos"]
    assert repo.db.execute("SELECT COUNT(*) FROM embedding_records").fetchone()[0] > 0
    warm = run_sync(photos, config)
    assert warm["duplicates"]["cache_hit"]
    assert warm["duplicates"]["embeddings"]["cache_hits"] == stored["eligible_photos"]
    cache.clear_derived(repo)
    assert repo.db.execute("SELECT COUNT(*) FROM embedding_records").fetchone()[0] == 0
    assert path.read_bytes() == b"offline fixture model"
    repo.close()
