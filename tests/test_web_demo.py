"""Bounded uploads, memory-only lifecycle, shared analyzers and public-safe UI."""

import io
import logging
from pathlib import Path

import pytest
from PIL import Image

from photocull.sources import FileImageSource, UploadedImageSource
from photocull.ui.style import bundled_sources
from photocull.web_session import (
    DECODE_EDGE,
    MAX_FILE_BYTES,
    MAX_IMAGES,
    MAX_PIXELS,
    MAX_THUMBNAIL_BYTES,
    MAX_TOTAL_BYTES,
    PROCESSING,
    REGISTRY,
    DemoBusyError,
    DemoLimitError,
    DemoSession,
    SessionRegistry,
    add_sources,
)


def source(name="image.png", size=(80, 40), color="red"):
    with io.BytesIO() as out:
        Image.new("RGB", size, color).save(out, "PNG")
        return UploadedImageSource(name, out.getvalue())


def test_upload_source_shares_local_decode_and_strips_private_metadata(photos):
    path = photos / "orientation.jpg"
    local, lm = FileImageSource(path).read(MAX_PIXELS)
    uploaded, um = UploadedImageSource("../../private/portrait.jpg", path.read_bytes()).read()
    assert local.size == uploaded.size == (40, 80)
    assert um["filename"] == "portrait.jpg" and um["path"] == "session-upload"
    assert um["filesystem_time"] is None and "mtime_ns" not in um
    assert um["capture_time"] == lm["capture_time"]
    assert local.tobytes() == uploaded.tobytes()
    local.close()
    uploaded.close()


def test_decode_pixel_bound_and_bounded_view():
    too_large = source(size=(3000, 3000))
    with pytest.raises(ValueError, match="pixel limit"):
        too_large.read()
    valid = source(size=(2600, 1800))
    image, metadata = valid.read()
    assert max(image.size) <= DECODE_EDGE
    assert metadata["width"] == 2600 and metadata["height"] == 1800
    image.close()


def test_file_total_count_and_attempt_limits():
    s = DemoSession()
    with pytest.raises(DemoLimitError, match="15 MiB"):
        s.add(UploadedImageSource("too-big.jpg", b"x" * (MAX_FILE_BYTES + 1)))
    with pytest.raises(DemoLimitError, match="nonempty"):
        s.add(UploadedImageSource("empty.png", b""))
    s.total_upload_bytes = MAX_TOTAL_BYTES
    with pytest.raises(DemoLimitError, match="60 MiB"):
        s.add(source())
    s.total_upload_bytes = 0
    for _ in range(MAX_IMAGES):
        assert s.add(source()) is not None
    with pytest.raises(DemoLimitError, match="30 images"):
        s.add(source())
    s.clear()
    with pytest.raises(DemoLimitError, match="expired"):
        s.add(source())
    attempts = DemoSession()
    attempts.attempts = 40
    with pytest.raises(DemoLimitError, match="attempt"):
        attempts.add(source())


def test_single_failure_does_not_abort_session_and_logs_no_content(caplog):
    s = DemoSession()
    with caplog.at_level(logging.DEBUG):
        assert s.add(UploadedImageSource("secret-location.jpg", b"corrupt private bytes")) is None
        assert s.add(source()) is not None
    assert len(s.failures) == 1 and len(s.photos) == 1
    assert all("secret-location" not in m and "private bytes" not in m for m in s.failures)
    assert "corrupt private bytes" not in caplog.text
    assert s.total_upload_bytes > len(source().data)
    s.analyze()
    assert s.events["unassigned_count"] == 1


def test_no_files_database_original_buffers_or_models_written(monkeypatch):
    import photocull.cache
    import photocull.storage

    def denied(*args, **kwargs):
        raise AssertionError("Web Demo cannot persist data")

    monkeypatch.setattr(photocull.cache.Cache, "__init__", denied)
    monkeypatch.setattr(photocull.storage.Repository, "__init__", denied)
    monkeypatch.setattr(Path, "write_bytes", denied)
    monkeypatch.setattr(Path, "write_text", denied)
    s = DemoSession()
    original = source()
    s.add(original)
    s.analyze()
    assert original.data not in s.thumbnails.values()
    assert all(len(t) <= MAX_THUMBNAIL_BYTES for t in s.thumbnails.values())
    assert not any(isinstance(v, UploadedImageSource) for v in vars(s).values())
    assert not hasattr(s, "embeddings")
    assert all(p.filesystem_time is None for p in s.photos)
    s.clear()
    assert not s.photos and not s.rows and not s.thumbnails and not s.preference_state


def test_semaphore_budget_and_session_isolation():
    a, b = DemoSession(), DemoSession()
    assert PROCESSING.acquire(blocking=False)
    try:
        with pytest.raises(DemoBusyError):
            a.add(source())
    finally:
        PROCESSING.release()
    assert a.attempts == 0
    a.add(source())
    assert not b.photos
    a.decisions["photo-001"] = "favorite"
    a.preference_state["feedback"] = [{"choice": "tie"}]
    a.clear()
    assert not a.decisions and not a.preference_state and not b.photos


def test_registry_ttl_capacity_and_disconnect_reference_cleanup():
    now = [0.0]
    registry = SessionRegistry(maximum=1, ttl=10, clock=lambda: now[0])
    a = registry.acquire()
    a.add(source())
    with pytest.raises(DemoBusyError):
        registry.acquire()
    now[0] = 11
    registry.purge()
    assert a.closed and not a.photos and not a.thumbnails
    b = registry.acquire()
    registry.release(b)
    assert not registry.leases
    c = registry.acquire()
    del c
    registry.purge()
    assert not registry.leases


def test_demo_dataset_groups_events_exports_and_memory_reset():
    s = DemoSession()
    add_sources(s, bundled_sources())
    assert len(s.photos) == 12 and s.events["event_count"] == 3
    assert {"EXACT_DUPLICATE", "NEAR_DUPLICATE", "BURST_GROUP"} <= {
        g["type"] for g in s.duplicates["groups"]
    }
    assert s.duplicates["statistics"]["expensive_comparisons"] <= 435
    assert s.ranking["selected"] and s.ranking["selected"][0]["explanation"]
    s.clear()
    assert not s.duplicates["groups"] and not s.ranking["selected"]


def test_web_ui_startup_demo_all_views_cleanup_and_embed(monkeypatch):
    from streamlit.testing.v1 import AppTest

    from photocull.storage import Repository

    def denied(*args, **kwargs):
        raise AssertionError("Public entry point cannot instantiate a repository")

    monkeypatch.setattr(Repository, "__init__", denied)
    app = AppTest.from_file(Path("streamlit_app.py").resolve(), default_timeout=20).run()
    assert not app.exception
    assert not app.text_input  # Never expose server folder paths.
    assert any("not intentionally persisted" in c.value for c in app.caption)
    next(b for b in app.button if b.label == "Try Demo Without Uploading Photos").click().run()
    assert not app.exception
    session = app.session_state["demo_session"]
    assert len(session.photos) == 12
    for view in ("Review", "Events", "Best Photos", "Preferences", "Export"):
        app.segmented_control[0].set_value(view).run()
        assert not app.exception
    assert any(b.label == "Download JSON manifest" for b in app.get("download_button"))
    session.preference_actions = 256
    app.segmented_control[0].set_value("Preferences").run()
    assert all(b.disabled for b in app.button if b.label in ("Prefer A", "Prefer B", "Tie", "Skip"))
    next(b for b in app.button if b.label == "Reset session preferences").click().run()
    assert session.preference_actions == 0
    next(b for b in app.button if b.label == "Clear temporary session").click().run()
    assert not app.exception and session.closed and not session.thumbnails
    assert len(app.session_state["demo_session"].photos) == 0
    app.query_params["compact"] = "true"
    app.run()
    assert not app.exception
    REGISTRY.release(app.session_state["demo_session"])


def test_optional_models_unavailable_default_core_survives(photos, config, monkeypatch):
    from dataclasses import replace

    from photocull.config import EmbeddingConfig, EventConfig
    from photocull.embeddings import EmbeddingService, ModelUnavailable
    from photocull.pipeline import run_sync

    def unavailable(*args, **kwargs):
        raise ModelUnavailable("Optional weights are unavailable")

    monkeypatch.setattr(EmbeddingService, "__init__", unavailable)
    configured = replace(
        config,
        embeddings=EmbeddingConfig(model="mobilenet"),
        events=EventConfig(method="dbscan", model="mobilenet"),
    )
    result = run_sync(photos, configured)
    assert result["stage"] == "finished" and result["ranking"]["selected_count"] > 0
    assert result["events"]["event_count"] > 0
    assert result["duplicates"]["embeddings"]["fallback"] == "hash-only"


def test_memory_failure_releases_worker_and_preserves_other_photos(monkeypatch):
    s = DemoSession()
    s.add(source())

    def no_memory(*args, **kwargs):
        raise MemoryError

    monkeypatch.setattr(UploadedImageSource, "read", no_memory)
    assert s.add(source()) is None and len(s.photos) == 1
    assert PROCESSING.acquire(blocking=False)
    PROCESSING.release()
    assert "memory" in s.failures[-1]


def test_analysis_failure_keeps_previous_results_and_releases_worker(monkeypatch):
    session = DemoSession()
    add_sources(session, bundled_sources())
    before = session.duplicates, session.events, session.ranking
    monkeypatch.setattr(
        "photocull.web_session.discover",
        lambda *a: (_ for _ in ()).throw(MemoryError()),
    )
    with pytest.raises(MemoryError):
        session.analyze()
    assert (session.duplicates, session.events, session.ranking) == before
    assert PROCESSING.acquire(blocking=False)
    PROCESSING.release()
    session.clear()


def test_bulk_demo_preflight_and_model_status(tmp_path):
    from photocull.cache import Cache
    from photocull.embeddings import model_status

    session = DemoSession()
    with pytest.raises(DemoLimitError):
        add_sources(session, [source()] * 31)
    assert not session.photos and session.total_upload_bytes == 0
    cache = Cache(tmp_path / "cache")
    assert not any(s["installed"] for s in model_status(cache).values())
    (cache.root / "models/mobilenet.pt").write_bytes(b"invalid checkpoint")
    assert "mismatch" in model_status(cache)["mobilenet"]["status"].lower()
