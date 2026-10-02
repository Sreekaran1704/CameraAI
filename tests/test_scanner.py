from pathlib import Path

import pytest
from PIL import Image

from photocull.scanner import PhotoScanner, SourceChangedError, content_hash, fingerprint


def test_discovery_and_corruption(photos):
    scanner = PhotoScanner()
    entries = list(scanner.discover(photos))
    assert sum(k == "supported" for k, _ in entries) == 18
    assert sum(k == "unsupported" for k, _ in entries) == 1
    with pytest.raises(OSError):
        scanner.read(photos / "corrupt.jpg", 80_000_000)


def test_orientation_exif_and_filesystem(photos):
    scanner = PhotoScanner()
    image, metadata = scanner.read(photos / "orientation.jpg", 80_000_000)
    assert image.size == (40, 80)
    assert metadata["orientation"] == 6
    assert metadata["original_width"] == 80
    assert Path(metadata["path"]).is_absolute()
    assert metadata["timestamp_provenance"] == "filesystem_mtime"
    image, burst = scanner.read(photos / "burst_1.jpg", 80_000_000)
    assert burst["capture_time"] == "2026-01-01T12:00:01"
    assert burst["capture_timezone"] == "-06:00"
    assert burst["timestamp_provenance"] == "exif"
    assert burst["mtime_ns"] > 0 and burst["file_size"] > 0


def test_symlinks_are_skipped(photos, tmp_path):
    (photos / "loop").symlink_to(photos, target_is_directory=True)
    (photos / "link.jpg").symlink_to(photos / "sharp.png")
    entries = list(PhotoScanner().discover(photos))
    assert sum(k == "symlink" for k, _ in entries) == 2
    assert len(entries) == 21


def test_changed_during_read(photos, monkeypatch):
    import photocull.scanner as module

    actual = module.load_image

    def changed(path, max_pixels):
        result = actual(path, max_pixels)
        with path.open("ab") as stream:
            stream.write(b"changed")
        return result

    monkeypatch.setattr(module, "load_image", changed)
    with pytest.raises(SourceChangedError):
        PhotoScanner().read(photos / "sharp.png", 80_000_000)


def test_unreadable_file_isolated(photos, monkeypatch):
    original = Path.open

    def deny(path, *args, **kwargs):
        if path.name == "sharp.png":
            raise PermissionError("Fixture permission denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny)
    with pytest.raises(PermissionError):
        PhotoScanner().read(photos / "sharp.png", 80_000_000)
    assert PhotoScanner().read(photos / "normal.png", 80_000_000)[0].size == (256, 256)


def test_fingerprints_and_hashes(photos):
    assert content_hash(photos / "sharp.png") == content_hash(photos / "exact.png")
    assert fingerprint(photos / "sharp.png") != fingerprint(photos / "exact.png")
    before = fingerprint(photos / "sharp.png")
    Image.new("RGB", (31, 32)).save(photos / "sharp.png")
    assert before != fingerprint(photos / "sharp.png")


def test_pixel_limits_and_cancelled_discovery(photos):
    with pytest.raises(ValueError, match="pixel limit"):
        PhotoScanner().read(photos / "sharp.png", 10)
    assert list(PhotoScanner().discover(photos, lambda: True)) == []


def test_unreadable_directory_error(photos, monkeypatch):
    import photocull.scanner as scanner

    real_walk = scanner.os.walk

    def walk_with_error(*args, **kwargs):
        kwargs["onerror"](PermissionError(13, "Permission denied", str(photos / "locked")))
        yield from real_walk(*args, **kwargs)

    monkeypatch.setattr(scanner.os, "walk", walk_with_error)
    entries = list(PhotoScanner().discover(photos))
    assert sum(k == "supported" for k, _ in entries) == 18
    assert sum(k == "discovery_error" for k, _ in entries) == 1
