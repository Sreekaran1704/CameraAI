import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from photocull.cli import main
from photocull.duplicate_evaluation import (
    binary_metrics,
    evaluate_duplicates,
    generate_duplicate_dataset,
    load_manifest,
)
from photocull.duplicate_storage import DuplicateStore
from photocull.duplicates import detect_for_scan, features_from_rows
from photocull.pipeline import run_sync
from photocull.similarity import SimilarityEngine
from photocull.storage import MIGRATION_1, Repository


def test_phase1_migration_preserves_decisions(tmp_path):
    path = tmp_path / "database.db"
    db = sqlite3.connect(path)
    db.executescript(MIGRATION_1)
    db.execute("INSERT INTO source_photos VALUES (1,'source','fp','sha','{}','fixture')")
    db.execute("INSERT INTO user_decisions VALUES (1,'keep','fixture')")
    db.commit()
    db.close()
    repo = Repository(path)
    assert repo.db.execute("PRAGMA user_version").fetchone()[0] == 6
    assert repo.db.execute("SELECT decision FROM user_decisions").fetchone()[0] == "keep"
    assert repo.db.execute("PRAGMA foreign_key_check").fetchall() == []
    repo.close()
    Repository(path).close()


def test_duplicate_cache_versions_source_invalidation(photos, config, monkeypatch):
    cold = run_sync(photos, config)
    assert not cold["duplicates"]["cache_hit"]
    warm = run_sync(photos, config)
    assert warm["duplicates"]["cache_hit"]
    updated = run_sync(
        photos, replace(config, duplicates=replace(config.duplicates, phash_distance=4))
    )
    assert not updated["duplicates"]["cache_hit"] and updated["cache_hits"] == 17
    monkeypatch.setattr(SimilarityEngine, "version", "duplicates_test_revision")
    versioned = run_sync(photos, config)
    assert not versioned["duplicates"]["cache_hit"]
    Image.new("RGB", (30, 32)).save(photos / "normal.png")
    changed = run_sync(photos, config)
    assert not changed["duplicates"]["cache_hit"] and changed["cache_hits"] == 16
    assert changed["failures"] == 1


def test_member_and_group_overrides_persist_and_clear_preserves(photos, config):
    run = run_sync(photos, config)
    repo = Repository(config.cache_dir / "metadata.db")
    store = DuplicateStore(repo)
    result = store.for_scan(run["run_id"])
    group = next(g for g in result["groups"] if len(g["members"]) >= 3)
    members = [
        p
        for p in features_from_rows(repo.results(run["run_id"]), verify=False)
        if p.id in group["members"]
    ]
    denied = group["members"][0]
    store.not_duplicate(members, denied)
    result = detect_for_scan(repo, run["run_id"], config)
    assert not result["cache_hit"]
    assert not any(denied in g["members"] for g in result["groups"])
    store.decide(members[1].id, "favorite")
    remaining = result["groups"][0]
    remaining_members = [p for p in members if p.id in remaining["members"]]
    store.not_duplicate(remaining_members)
    result = detect_for_scan(repo, run["run_id"], config)
    assert remaining["signature"] not in {g["signature"] for g in result["groups"]}
    repo.clear_derived()
    assert repo.db.execute("SELECT COUNT(*) FROM not_duplicate_pairs").fetchone()[0] == 2
    assert repo.db.execute("SELECT COUNT(*) FROM not_duplicate_groups").fetchone()[0] == 1
    assert repo.db.execute("SELECT decision FROM user_decisions").fetchone()[0] == "favorite"
    assert repo.db.execute("SELECT COUNT(*) FROM duplicate_runs").fetchone()[0] == 0
    repo.close()


def test_fingerprint_scoped_override_expires(photos, config):
    run = run_sync(photos, config)
    repo = Repository(config.cache_dir / "metadata.db")
    store = DuplicateStore(repo)
    members = features_from_rows(repo.results(run["run_id"]), verify=False)
    store.not_duplicate(members[:2], members[0].id)
    assert store.corrections(members)[0]
    members[0].fingerprint = "new-source-version"
    assert not store.corrections(members)[0]
    repo.close()


def test_duplicate_cli_json(photos, config, capsys):
    assert main(["--cache-dir", str(config.cache_dir), "duplicates", str(photos)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["detection"]["groups"] and result["detection"]["analysis_id"]


def test_duplicate_review_app(photos, config, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("PHOTOCULL_CACHE_DIR", str(config.cache_dir))
    run_sync(photos, config)
    app = AppTest.from_file(Path("src/photocull/ui/app.py").resolve(), default_timeout=15).run()
    app.sidebar.radio[0].set_value("Duplicate Review").run()
    assert not app.exception
    assert app.metric[0].value == "1"
    assert any(b.label == "Favorite" for b in app.button)
    next(b for b in app.button if b.label == "Favorite").click().run()
    assert not app.exception
    repo = Repository(config.cache_dir / "metadata.db")
    assert repo.db.execute("SELECT decision FROM user_decisions").fetchone()[0] == "favorite"
    repo.close()


def test_metrics_and_empty_prediction():
    assert binary_metrics([True, True, False], [True, False, True])["precision"] == 0.5
    assert binary_metrics([True], [False])["precision"] is None


def test_manifest_splits_and_evaluation(tmp_path):
    generate_duplicate_dataset(tmp_path / "dataset", families=2)
    path = tmp_path / "dataset" / "manifest.json"
    report = evaluate_duplicates(path)
    assert report["held_out"]["metrics"]["exact"]["recall"] == 1
    assert report["development"]["metrics"]["near"]["precision"] >= 0.98
    assert len(report["threshold_experiment"]) == 7
    assert len(report["burst_experiment"]) == 3
    manifest = json.loads(path.read_text())
    manifest["photos"][0]["family"] = manifest["photos"][-1]["family"]
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="leakage"):
        load_manifest(path)


def test_manifest_group_labels_and_content_leakage(tmp_path):
    folder = tmp_path / "dataset"
    generate_duplicate_dataset(folder, families=1)
    path = folder / "manifest.json"
    manifest = json.loads(path.read_text())
    pair = next(p for p in manifest["pairs"] if p["label"] == "EXACT_DUPLICATE")
    manifest["pairs"].remove(pair)
    manifest["groups"] = [
        {"members": [pair["a"], pair["b"]], "label": pair["label"], "split": pair["split"]}
    ]
    path.write_text(json.dumps(manifest))
    loaded, _ = load_manifest(path)
    assert any(p["a"] == pair["a"] and p["b"] == pair["b"] for p in loaded["pairs"])
    original = next(p for p in manifest["photos"] if p["id"] == pair["a"])
    held_out = next(p for p in manifest["photos"] if p["split"] == "held_out")
    held_out["path"] = original["path"]
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Byte-identical"):
        load_manifest(path)


def test_generated_phase2_fixtures_deterministic(tmp_path):
    from photocull.scanner import content_hash

    a, b = tmp_path / "a", tmp_path / "b"
    generate_duplicate_dataset(a, families=1)
    generate_duplicate_dataset(b, families=1)
    assert {p.name: content_hash(p) for p in (a / "photos").iterdir()} == {
        p.name: content_hash(p) for p in (b / "photos").iterdir()
    }


def test_real_hardlinks_do_not_inflate_savings(photos, config):
    import os

    os.link(photos / "sharp.png", photos / "linked.png")
    run = run_sync(photos, config)
    repo = Repository(config.cache_dir / "metadata.db")
    rows = features_from_rows(repo.results(run["run_id"]), verify=False)
    links = [p for p in rows if p.filename in {"sharp.png", "linked.png"}]
    assert len(links) == 2 and links[0].storage_identity == links[1].storage_identity
    assert all(p.link_count == 2 for p in links)
    result = DuplicateStore(repo).for_scan(run["run_id"])
    assert result["exact_reclaimable_bytes"] <= 2 * (photos / "exact.png").stat().st_size
    repo.close()


def test_verification_cache_corruption_isolated(photos, config):
    run = run_sync(photos, config)
    repo = Repository(config.cache_dir / "metadata.db")
    rows = repo.results(run["run_id"])
    Path(rows[0]["thumbnail"]["path"]).write_bytes(b"invalid thumbnail")
    features = features_from_rows(rows)
    assert len(features) == 17 and features[0].verification is None
    repo.close()
