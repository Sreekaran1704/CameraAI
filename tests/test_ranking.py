"""Offline ranking, guardrail, persistence and export contracts."""

import csv
import io
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from photocull.config import RankingConfig
from photocull.duplicate_storage import DuplicateStore
from photocull.pipeline import run_sync
from photocull.ranking import export_manifest, rank, shortlist
from photocull.ranking_service import cached_vectors, prepare, recommend
from photocull.similarity import PhotoFeatures
from photocull.storage import Repository


def photo(identifier, q=0.5):
    return PhotoFeatures(
        str(identifier),
        f"fp-{identifier}",
        f"sha-{identifier}",
        100,
        100,
        1000,
        {"phash": f"{identifier * 1000003:016x}"},
        {"technical_quality_v1": q, "normalized": {"sharpness": q, "exposure": q, "resolution": q}},
        f"2025-01-01T{10 + identifier // 10:02d}:00:00+00:00",
    )


def test_quality_only_and_duplicate_context_ignore_uniqueness():
    photos = [photo(1, 0.9), photo(2, 0.3), photo(3, 0.6)]
    baseline = rank(photos, RankingConfig(variant="A"))
    duplicate = rank(photos, context="duplicate")
    assert [r["photo_id"] for r in baseline["ranked"]] == ["1", "3", "2"]
    assert [r["photo_id"] for r in duplicate["ranked"]] == ["1", "3", "2"]
    assert all(r["weights"] == [1, 0, 0] for r in duplicate["ranked"])


def test_representation_and_guarded_uniqueness():
    photos = [photo(1), photo(2), photo(3, 0.1)]
    vectors = {"1": np.array([1.0, 0]), "2": np.array([1.0, 0]), "3": np.array([0.0, 1])}
    result = rank(photos, vectors=vectors)
    rows = {r["photo_id"]: r for r in result["ranked"]}
    assert rows["1"]["representation"] > rows["3"]["representation"]
    assert rows["1"]["uniqueness"] == 0
    assert rows["3"]["uniqueness"] == 0
    photos[2].quality["technical_quality_v1"] = 0.7
    assert all(r["uniqueness"] <= 0.25 for r in rank(photos, vectors=vectors)["ranked"])


def test_diversity_and_known_duplicate_suppression():
    photos = [photo(1, 0.8), photo(2, 0.79), photo(3, 0.75)]
    vectors = {"1": np.array([1.0, 0]), "2": np.array([1.0, 0]), "3": np.array([0.0, 1])}
    cfg = RankingConfig(
        quality_weight=1,
        representation_weight=0,
        uniqueness_weight=0,
        diversity_penalty=0.4,
        coverage_bonus=0,
    )
    ranked = rank(photos, cfg, vectors=vectors)
    diverse = shortlist(photos, ranked["ranked"], 2, cfg, vectors)
    assert [r["photo_id"] for r in diverse["selected"]] == ["1", "3"]
    groups = [{"members": ["1", "2"], "type": "NEAR_DUPLICATE"}]
    result = shortlist(photos, ranked["ranked"], 3, cfg, vectors, groups)
    assert len(result["selected"]) == 2 and result["shorter_than_requested"]


def test_soft_coverage_never_forces_low_quality():
    photos = [photo(1, 0.8), photo(2, 0.8), photo(3, 0.79), photo(4, 0.1)]
    cfg = RankingConfig(
        quality_weight=1,
        representation_weight=0,
        uniqueness_weight=0,
        diversity_penalty=0,
        coverage_bonus=0.1,
    )
    result = shortlist(
        photos,
        rank(photos, cfg)["ranked"],
        2,
        cfg,
        coverage={"1": "a", "2": "a", "3": "b", "4": "c"},
    )
    assert [r["photo_id"] for r in result["selected"]] == ["1", "3"]


def test_ties_stable_empty_small_and_invalid_input():
    photos = [photo(2), photo(1)]
    assert rank(photos)["ranked"] == rank(list(reversed(photos)))["ranked"]
    assert rank([])["ranked"] == []
    assert shortlist([], [], 10)["selected"] == []
    assert len(shortlist([photo(1)], rank([photo(1)])["ranked"], 10)["selected"]) == 1
    with pytest.raises(ValueError):
        shortlist(photos, rank(photos)["ranked"], -1)
    with pytest.raises(ValueError):
        RankingConfig(variant="C")
    with pytest.raises(ValueError):
        RankingConfig(quality_weight=float("nan"))


def test_export_schema_labels_and_formula_guard():
    selected = shortlist([photo(1)], rank([photo(1)])["ranked"], 1)["selected"]
    rows = {"1": {"path": "/local/one.jpg", "metadata": {"filename": "=formula.jpg"}}}
    payload = export_manifest(selected, rows, {"1": "Event 01"}, {"1": "favorite"})
    assert json.loads(payload)[0]["source_name"] == "=formula.jpg"
    assert json.loads(payload)[0]["user_label"] == "favorite"
    csvrows = list(
        csv.DictReader(
            io.StringIO(
                export_manifest(selected, rows, {"1": "Event 01"}, {"1": "favorite"}, "csv")
            )
        )
    )
    assert csvrows[0]["source_name"] == "'=formula.jpg"
    assert "explanation" in csvrows[0] and "quality_metrics" in csvrows[0]
    assert export_manifest([], {}, {}, {}, "json") == "[]"


def test_cache_version_event_corrections_and_favorites(photos, config, monkeypatch):
    run = run_sync(photos, config)
    repo = Repository(config.cache_dir / "metadata.db")
    data = prepare(repo, run["run_id"], config)
    first = recommend(repo, config, data)
    second = recommend(repo, config, data)
    assert first["cache_hit"] and second["cache_hit"]
    identifier = data["photos"][0].id
    DuplicateStore(repo).decide(int(identifier), "favorite")
    updated = prepare(repo, run["run_id"], config)
    assert updated["decisions"][identifier] == "favorite"
    assert recommend(repo, config, updated)["ranked"] == first["ranked"]
    import photocull.ranking_service as service

    monkeypatch.setattr(service, "VERSION", "ranking_test_v2")
    assert not recommend(repo, config, updated)["cache_hit"]
    changed = replace(config, ranking=replace(config.ranking, diversity_penalty=0.4))
    assert not recommend(repo, changed, updated)["cache_hit"]
    repo.clear_derived()
    assert repo.db.execute("SELECT COUNT(*) FROM ranking_results").fetchone()[0] == 0
    assert (
        repo.db.execute(
            "SELECT decision FROM user_decisions WHERE photo_id=?", (identifier,)
        ).fetchone()[0]
        == "favorite"
    )
    repo.close()


def test_cached_embeddings_no_inference_and_bad_records(photos, config):
    from photocull.cache import Cache
    from photocull.embeddings import CHECKSUMS, MODELS

    run = run_sync(photos, config)
    repo = Repository(config.cache_dir / "metadata.db")
    data = prepare(repo, run["run_id"], config)
    p = data["photos"][0]
    cache = Cache(config.cache_dir)
    key = "b" * 64
    vector = np.ones(512, dtype=np.float32) / np.sqrt(512)
    path = cache.root / "embeddings" / f"{key}.npy"
    np.save(path, vector)
    analysis = repo.version("EmbeddingFixture", "v1", {})
    with repo.db:
        repo.db.execute(
            "INSERT INTO embedding_records(cache_key,photo_id,fingerprint,model_id,checksum,"
            "preprocessing,analysis_id,path,dimension,device) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                key,
                int(p.id),
                p.fingerprint,
                "tinyclip",
                CHECKSUMS["tinyclip"],
                MODELS["tinyclip"].preprocessing,
                analysis,
                str(path),
                512,
                "cpu",
            ),
        )
    vectors, stats = cached_vectors(repo, cache, [p], "tinyclip")
    assert stats["hits"] == 1 and stats["inference_performed"] is False
    assert np.allclose(vectors[p.id], vector)
    np.save(path, np.array([float("nan")]))
    assert not cached_vectors(repo, cache, [p], "tinyclip")[0]
    repo.close()


def test_best_photos_ui_and_favorites(photos, config, monkeypatch):
    from streamlit.testing.v1 import AppTest

    run = run_sync(photos, config)
    monkeypatch.setenv("PHOTOCULL_CACHE_DIR", str(config.cache_dir))
    repo = Repository(config.cache_dir / "metadata.db")
    data = prepare(repo, run["run_id"], config)
    identifiers = data["groups"][0]["members"][:2]
    for identifier in identifiers:
        DuplicateStore(repo).decide(int(identifier), "favorite")
    repo.close()
    app = AppTest.from_file(Path("src/photocull/ui/app.py").resolve(), default_timeout=15).run()
    app.radio[0].set_value("Best Photos").run()
    assert not app.exception
    assert any(b.label == "Export JSON manifest" for b in app.get("download_button"))
    next(x for x in app.selectbox if x.label == "View").set_value("Favorites").run()
    assert not app.exception
    assert len(next(x for x in app.multiselect if x.label == "Export selection").value) == 2


def test_manual_event_membership_invalidates_library_ranking(photos, config):
    from photocull.event_storage import EventStore

    run = run_sync(photos, config)
    repo = Repository(config.cache_dir / "metadata.db")
    data = prepare(repo, run["run_id"], config)
    assert recommend(repo, config, data)["cache_hit"]
    event = data["events"]["events"][0]
    EventStore(repo).correct(data["events"], "rename", event_id=event["id"], name="Corrected event")
    updated = prepare(repo, run["run_id"], config)
    assert not recommend(repo, config, updated)["cache_hit"]
    assert any(e["name"] == "Corrected event" for e in updated["events"]["events"])
    repo.close()
