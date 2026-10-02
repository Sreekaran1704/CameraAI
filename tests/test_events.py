"""Event contracts and correction persistence, with all sockets denied by conftest."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from photocull.config import Config, EventConfig
from photocull.duplicates import features_from_rows
from photocull.event_evaluation import generate_events, load_events, metrics
from photocull.event_storage import EventStore
from photocull.events import discover, discover_for_scan, representatives
from photocull.pipeline import run_sync
from photocull.similarity import PhotoFeatures
from photocull.storage import Repository


def photo(identifier, minutes=0, capture=True, fs=None):
    time = datetime(2025, 1, 1, 12, tzinfo=UTC) + timedelta(minutes=minutes)
    return PhotoFeatures(
        str(identifier),
        f"fp-{identifier}",
        f"sha-{identifier}",
        256,
        256,
        10000,
        {"phash": f"{int(identifier) * 1000003:016x}"},
        {"technical_quality_v1": 0.5},
        time.isoformat() if capture else None,
        filesystem_time=fs,
    )


def test_gap_boundary_and_singletons():
    result = discover(
        [photo(1), photo(2, 30), photo(3, 61), photo(4, 600)], EventConfig(gap_minutes=30)
    )
    assert sorted(len(e["members"]) for e in result["events"]) == [1, 1, 2]
    assert result["assignments"]["4"]["status"] == "EVENT_MEMBER"


def test_timezone_normalization_and_tier_isolation():
    left, right, naive, fs = photo(1), photo(2), photo(3), photo(4, capture=False)
    right.capture_time = "2025-01-01T07:03:00-05:00"
    naive.capture_time = "2025-01-01T12:03:00"
    fs.filesystem_time = right.capture_time
    result = discover([left, right, naive, fs])
    assert result["assignments"]["1"]["event_id"] == result["assignments"]["2"]["event_id"]
    assert result["event_count"] == 3
    assert result["assignments"]["3"]["timestamp_confidence"] == "medium"
    assert result["assignments"]["4"]["status"] == "LOW_CONFIDENCE"


def test_missing_invalid_and_filesystem_awareness():
    missing = photo(1, capture=False)
    invalid = photo(2, capture=False)
    invalid.capture_time = "invalid"
    aware = photo(3, capture=False, fs="2025-01-01T12:00:00+00:00")
    naive = photo(4, capture=False, fs="2025-01-01T12:00:00")
    result = discover([missing, invalid, aware, naive])
    assert result["unassigned_count"] == 2
    assert result["event_count"] == 2


def test_maximum_span_prevents_unbounded_chaining():
    result = discover([photo(i, i * 60) for i in range(30)], EventConfig(gap_minutes=120))
    assert result["event_count"] == 2


def test_visual_outlier_and_missing_vector():
    photos = [photo(i, i * 2) for i in range(1, 5)]
    vectors = {"1": np.array([1.0, 0]), "2": np.array([1.0, 0]), "3": np.array([0.0, 1])}
    result = discover(photos, EventConfig(method="dbscan", model="mobilenet"), vectors)
    assert result["event_count"] == 1
    assert result["unassigned_count"] == 2
    assert result["assignments"]["3"]["event_id"] is None
    assert "unavailable" in result["assignments"]["4"]["reason"]


def test_visual_supports_long_event_without_merging_different_days():
    photos = [photo(1), photo(2, 150), photo(3, 1440), photo(4, 1442)]
    vectors = {p.id: np.array([1.0, 0]) for p in photos}
    baseline = discover(photos, EventConfig(gap_minutes=60))
    visual = discover(
        photos,
        EventConfig(method="dbscan", model="mobilenet", time_weight=0.1, visual_weight=0.9),
        vectors,
    )
    assert baseline["event_count"] == 3
    assert visual["event_count"] == 2


def test_pure_visual_control_can_cross_days():
    photos = [photo(1), photo(2, 1440)]
    vectors = {p.id: np.array([1.0, 0]) for p in photos}
    result = discover(
        photos, EventConfig(method="dbscan", model="mobilenet", pure_visual=True), vectors
    )
    assert result["event_count"] == 1


def test_bounded_density_reports_uncertainty():
    photos = [photo(i) for i in range(10)]
    vectors = {p.id: np.array([1.0, 0]) for p in photos}
    result = discover(
        photos, EventConfig(method="dbscan", model="mobilenet", candidate_neighbors=2), vectors
    )
    assert result["candidate_comparisons"] <= len(photos) * 2
    assert result["candidate_search_truncated"]
    assert result["low_confidence_count"] == 10


def test_hdbscan_bounds_large_windows():
    photos = [photo(i) for i in range(10)]
    result = discover(
        photos,
        EventConfig(method="hdbscan", model="mobilenet", hdbscan_window_limit=4),
        {p.id: np.array([1.0, 0]) for p in photos},
    )
    assert result["unassigned_count"] == 10 and result["warnings"]


def test_representatives_central_quality_tie_and_duplicate_suppression():
    photos = [photo(i) for i in range(1, 5)]
    photos[1].sha256 = photos[0].sha256
    photos[0].quality["technical_quality_v1"] = 0.9
    vectors = {p.id: np.array([1.0, 0]) for p in photos}
    selected = representatives(photos, vectors)
    assert selected[0] == "1"
    assert "2" not in selected and len(selected) == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"gap_minutes": 0},
        {"max_span_hours": 25},
        {"time_weight": 0.8},
        {"candidate_neighbors": 0},
        {"method": "kmeans"},
        {"method": "dbscan", "model": "disabled"},
        {"epsilon": float("nan")},
    ],
)
def test_invalid_event_configuration(changes):
    with pytest.raises(ValueError):
        EventConfig(**changes)


def analyzed(tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    for i in range(6):
        exif = Image.Exif()
        exif[36867] = f"2025:01:01 {10 if i < 3 else 16}:0{i % 3}:00"
        exif[36881] = "+00:00"
        Image.new("RGB", (128, 128), (i * 30, 100, 70)).save(folder / f"{i}.jpg", exif=exif)
    config = Config(cache_dir=tmp_path / "cache")
    run = run_sync(folder, config)
    assert run["failures"] == 0
    repo = Repository(config.cache_dir / "metadata.db")
    photos = features_from_rows(repo.results(run["run_id"]), verify=False)
    store = EventStore(repo)
    result = store.for_scan(run["run_id"], photos)
    return folder, config, run, repo, photos, store, result


def test_manual_rename_split_merge_remove_move_survive_reruns(tmp_path):
    folder, config, run, repo, photos, store, result = analyzed(tmp_path)
    first, second = result["events"]
    store.correct(result, "rename", event_id=first["id"], name="My event")
    result = store.for_scan(run["run_id"], photos)
    first = next(e for e in result["events"] if e["name"] == "My event")
    selected = first["members"][:1]
    store.correct(result, "split", event_id=first["id"], photo_ids=selected, name="Split")
    result = store.for_scan(run["run_id"], photos)
    assert result["event_count"] == 3
    split = next(e for e in result["events"] if e["name"] == "Split")
    other = next(e for e in result["events"] if e["id"] == second["id"])
    store.correct(result, "merge", event_id=split["id"], target_id=other["id"])
    result = store.for_scan(run["run_id"], photos)
    assert result["event_count"] == 2
    store.correct(result, "remove", photo_ids=selected)
    repo.close()
    rerun = run_sync(folder, replace(config, events=replace(config.events, gap_minutes=720)))
    repo = Repository(config.cache_dir / "metadata.db")
    store = EventStore(repo)
    photos = features_from_rows(repo.results(rerun["run_id"]), verify=False)
    result = store.for_scan(rerun["run_id"], photos)
    assert any(e["name"] == "My event" for e in result["events"])
    assert result["assignments"][selected[0]]["event_id"] is None
    target = result["events"][0]["id"]
    store.correct(result, "move", target_id=target, photo_ids=selected)
    result = store.for_scan(rerun["run_id"], photos)
    assert result["assignments"][selected[0]]["manual"]
    assert result["assignments"][selected[0]]["event_id"] is not None
    repo.clear_derived()
    assert repo.db.execute("SELECT COUNT(*) FROM event_overrides").fetchone()[0] == 6
    assert not repo.db.execute("SELECT COUNT(*) FROM event_runs").fetchone()[0]
    repo.close()


def test_manual_fingerprint_conflict_is_explicit(tmp_path):
    _, _, run, repo, photos, store, result = analyzed(tmp_path)
    store.correct(result, "rename", event_id=result["events"][0]["id"], name="Named")
    photos[0].fingerprint = "changed"
    corrected = store.for_scan(run["run_id"], photos)
    assert photos[0].id in corrected["manual_correction_conflicts"]
    assert corrected["assignments"][photos[0].id]["status"] == "LOW_CONFIDENCE"
    repo.close()


def test_live_source_change_rejects_old_manual_snapshot(tmp_path):
    folder, _, _, repo, _, store, result = analyzed(tmp_path)
    Image.new("RGB", (150, 150), "red").save(folder / "0.jpg")
    with pytest.raises(ValueError, match="Sources changed"):
        store.correct(result, "rename", event_id=result["events"][0]["id"], name="Old")
    assert not repo.db.execute("SELECT COUNT(*) FROM event_overrides").fetchone()[0]
    repo.close()


def test_event_version_and_parameter_invalidation(tmp_path, monkeypatch):
    _, config, run, repo, _, _, _ = analyzed(tmp_path)
    assert discover_for_scan(repo, run["run_id"], config)["cache_hit"]
    import photocull.events as module

    monkeypatch.setattr(module, "VERSION", "test-v2")
    assert not discover_for_scan(repo, run["run_id"], config)["cache_hit"]
    changed = replace(config, events=replace(config.events, gap_minutes=15))
    assert not discover_for_scan(repo, run["run_id"], changed)["cache_hit"]
    repo.close()


def test_missing_model_falls_back_without_changing_duplicates(tmp_path):
    folder, config, _, repo, _, _, _ = analyzed(tmp_path)
    repo.close()
    changed = replace(config, events=EventConfig(method="dbscan", model="tinyclip"))
    result = run_sync(folder, changed)
    assert result["events"]["embeddings"]["fallback"] == "time"
    assert not result["duplicates"]["embeddings"]["enabled"]


def test_fixture_family_separation_noise_and_metrics(tmp_path):
    folder = tmp_path / "events"
    generate_events(folder)
    manifest, photos, _ = load_events(folder / "manifest.json")
    dev = {r["family"] for r in manifest["photos"] if r["split"] == "dev"}
    test = {r["family"] for r in manifest["photos"] if r["split"] == "test"}
    assert not dev & test and len(photos) == 488
    result = discover(photos)
    score = metrics(manifest["photos"], result)
    assert 0 <= score["ari"] <= 1 and score["noise_count"] == 8


def test_events_ui_smoke_and_rename(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    _, config, _, repo, _, _, _ = analyzed(tmp_path)
    repo.close()
    monkeypatch.setenv("PHOTOCULL_CACHE_DIR", str(config.cache_dir))
    app = AppTest.from_file(Path("src/photocull/ui/app.py").resolve(), default_timeout=15).run()
    app.radio[0].set_value("Events").run()
    assert not app.exception
    assert app.metric[0].value == "2"
    next(x for x in app.text_input if x.label == "Event name").set_value("UI event")
    next(x for x in app.button if x.label == "Save name").click().run()
    assert not app.exception
    assert any("UI event" in x.value for x in app.markdown)


def test_stale_sources_excluded_from_saved_event_view(tmp_path):
    folder, _, run, repo, _, store, _ = analyzed(tmp_path)
    Image.new("RGB", (150, 150), "red").save(folder / "0.jpg")
    valid = features_from_rows(repo.results(run["run_id"]), verify=False)
    corrected = store.for_scan(run["run_id"], valid)
    assert len(corrected["assignments"]) == 5
    assert corrected["excluded_unavailable_since_event_run"] == 1
    assert sum(len(e["members"]) for e in corrected["events"]) == 5
    repo.close()


def test_visual_representatives_preserved_without_loading_vectors(tmp_path):
    _, _, _, repo, photos, store, _ = analyzed(tmp_path)
    config = EventConfig(method="dbscan", model="mobilenet")
    vectors = {p.id: np.array([1.0, 0]) for p in photos}
    automatic = discover(photos, config, vectors)
    corrected = store.overlay(automatic, photos)
    assert corrected["events"][0]["representatives"] == automatic["events"][0]["representatives"]
    assert "centroid" in corrected["events"][0]["representative_reason"]
    repo.close()


def test_event_config_old_snapshot_and_cancellation():
    snapshot = Config().snapshot()
    snapshot.pop("events")
    restored = Config.from_snapshot(snapshot)
    assert restored.events == EventConfig()
    with pytest.raises(InterruptedError):
        discover([photo(1)], cancelled=lambda: True)
