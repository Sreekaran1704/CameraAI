import json
from dataclasses import replace

import pytest
from PIL import Image

from photocull.cache import Cache
from photocull.config import QualityConfig
from photocull.pipeline import run_sync
from photocull.scanner import content_hash
from photocull.storage import Repository


def test_migration_idempotence(config):
    cache = Cache(config.cache_dir)
    for _ in range(2):
        repo = Repository(cache.root / "metadata.db")
        assert repo.db.execute("PRAGMA user_version").fetchone()[0] == 6
        assert repo.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        names = {r[0] for r in repo.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {
            "source_photos",
            "scan_runs",
            "analysis_versions",
            "quality_measurements",
            "perceptual_hashes",
            "thumbnail_metadata",
            "processing_failures",
            "user_decisions",
            "run_photos",
        } <= names
        repo.close()


def test_cache_hits_invalidation_and_provenance(photos, config, monkeypatch):
    cold = run_sync(photos, config)
    assert cold["analyzed"] == 17 and cold["failures"] == 1 and cold["cache_hits"] == 0
    import photocull.scanner as scanner

    original_hash = scanner.content_hash
    calls = []

    def record(path):
        calls.append(path)
        return original_hash(path)

    monkeypatch.setattr(scanner, "content_hash", record)
    warm = run_sync(photos, config)
    assert warm["cache_hits"] == 17 and not calls
    changed_config = replace(config, quality=QualityConfig(blur_warning_score=0.2))
    updated = run_sync(photos, changed_config)
    assert updated["cache_hits"] == 0 and updated["component_cache_hits"] == 34
    assert not calls
    Image.new("RGB", (99, 101), "blue").save(photos / "normal.png")
    invalidated = run_sync(photos, changed_config)
    assert invalidated["cache_hits"] == 16 and calls == [photos / "normal.png"]
    repo = Repository(config.cache_dir / "metadata.db")
    results = repo.results(updated["run_id"])
    assert any(r["source_changed_since_run"] for r in results)
    versions = repo.db.execute("SELECT * FROM analysis_versions").fetchall()
    assert len(versions) == 7
    row = repo.db.execute("SELECT * FROM quality_measurements LIMIT 1").fetchone()
    assert row["fingerprint"] and row["generated_at"] and row["analysis_id"]
    assert json.loads(row["raw_json"]) and json.loads(row["normalized_json"])
    repo.close()


def test_thumbnail_orientation_bounds_and_cache(photos, config):
    first = run_sync(photos, config)
    repo = Repository(config.cache_dir / "metadata.db")
    rows = repo.results(first["run_id"])
    for row in rows:
        with Image.open(row["thumbnail"]["path"]) as thumbnail:
            assert max(thumbnail.size) <= config.thumbnail_edge
    oriented = next(r for r in rows if r["metadata"]["filename"] == "orientation.jpg")
    assert (oriented["thumbnail"]["width"], oriented["thumbnail"]["height"]) == (40, 80)
    thumb = oriented["thumbnail"]["path"]
    from pathlib import Path

    Path(thumb).unlink()
    second = run_sync(photos, config)
    assert second["cache_hits"] == 16
    assert second["component_cache_hits"] == 50
    assert Path(thumb).is_file()
    repo.close()


def test_clear_preserves_sources_and_decisions(photos, config):
    before = {p.name: content_hash(p) for p in photos.iterdir()}
    run_sync(photos, config)
    repo = Repository(config.cache_dir / "metadata.db")
    with repo.db:
        repo.db.execute("INSERT INTO user_decisions VALUES (1,'keep','fixture')")
    Cache(config.cache_dir).clear_derived(repo)
    assert repo.counts()["quality_measurements"] == 0
    assert repo.counts()["perceptual_hashes"] == 0
    assert repo.counts()["thumbnail_metadata"] == 0
    assert repo.counts()["source_photos"] == 17
    assert repo.counts()["user_decisions"] == 1
    assert not list((config.cache_dir / "thumbnails").iterdir())
    assert before == {p.name: content_hash(p) for p in photos.iterdir()}
    repo.close()


@pytest.mark.parametrize("kind", ["root", "ancestor", "derived", "nested", "database"])
def test_symlink_cleanup_refused(tmp_path, kind):
    target = tmp_path / "outside"
    target.mkdir()
    (target / "original.jpg").write_bytes(b"original")
    if kind == "root":
        link = tmp_path / "cache"
        link.symlink_to(target, target_is_directory=True)
        with pytest.raises(ValueError):
            Cache(link)
    elif kind == "ancestor":
        link = tmp_path / "link"
        link.symlink_to(target, target_is_directory=True)
        with pytest.raises(ValueError):
            Cache(link / "cache")
    else:
        cache = Cache(tmp_path / "cache")
        repo = Repository(cache.root / "metadata.db")
        if kind == "derived":
            (cache.root / "thumbnails").rmdir()
            (cache.root / "thumbnails").symlink_to(target, target_is_directory=True)
        elif kind == "nested":
            (cache.root / "thumbnails" / "trap.jpg").symlink_to(target / "original.jpg")
        else:
            repo.close()
            (cache.root / "metadata.db").unlink()
            (cache.root / "metadata.db").symlink_to(target / "original.jpg")
            with pytest.raises(ValueError):
                Repository(cache.root / "metadata.db")
            return
        with pytest.raises(ValueError):
            cache.clear_derived(repo)
        repo.close()
    assert (target / "original.jpg").read_bytes() == b"original"


def test_cache_source_overlap_and_busy(photos, config):
    cache = Cache(config.cache_dir)
    with pytest.raises(ValueError):
        cache.assert_source(config.cache_dir)
    with pytest.raises(ValueError):
        cache.assert_source(config.cache_dir.parent)
    with pytest.raises(ValueError):
        Cache(photos)
    repo = Repository(cache.root / "metadata.db")
    with cache.lock(), pytest.raises(ValueError, match="busy"):
        cache.clear_derived(repo)
    repo.close()


def test_thorough_recomputes_everything(photos, config):
    run_sync(photos, config)
    result = run_sync(photos, config, thorough=True)
    assert result["analyzed"] == 17 and result["cache_hits"] == 0
    assert result["component_cache_hits"] == 0


def test_algorithm_version_invalidation(photos, config, monkeypatch):
    from photocull.quality import QualityAnalyzer

    original = run_sync(photos, config)
    monkeypatch.setattr(QualityAnalyzer, "version", "technical_quality_v1-test-revision")
    revised = run_sync(photos, config)
    assert revised["cache_hits"] == 0 and revised["component_cache_hits"] == 34
    repo = Repository(config.cache_dir / "metadata.db")
    # Historic results still point at the exact analysis used during the old run.
    assert (
        repo.results(original["run_id"])[0]["quality"]["analysis_id"]
        != repo.results(revised["run_id"])[0]["quality"]["analysis_id"]
    )
    repo.close()


def test_unknown_file_cleanup_refused(photos, config):
    run_sync(photos, config)
    unexpected = config.cache_dir / "thumbnails" / "original.jpg"
    unexpected.write_bytes(b"preserve")
    repo = Repository(config.cache_dir / "metadata.db")
    with pytest.raises(ValueError, match="Unexpected"):
        Cache(config.cache_dir).clear_derived(repo)
    assert unexpected.read_bytes() == b"preserve"
    assert repo.counts()["quality_measurements"] == 17
    repo.close()


def test_source_change_detected_without_rescan(photos, config):
    run = run_sync(photos, config)
    Image.new("RGB", (32, 33)).save(photos / "normal.png")
    repo = Repository(config.cache_dir / "metadata.db")
    row = next(r for r in repo.results(run["run_id"]) if r["metadata"]["filename"] == "normal.png")
    assert row["source_changed_since_run"]
    repo.close()
