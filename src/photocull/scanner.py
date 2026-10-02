"""Read-only file discovery and metadata extraction."""

import hashlib
import os
from pathlib import Path

from PIL import Image

from photocull.config import parameter_hash

SUPPORTED = {".jpg", ".jpeg", ".png", ".webp"}
FORMATS = {"JPEG", "PNG", "WEBP"}


class SourceChangedError(OSError):
    pass


def fingerprint(path: Path) -> str:
    stat = path.stat()
    return parameter_hash(
        {"path": str(path.resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    )


def content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_image(path: Path, max_pixels: int) -> tuple[Image.Image, dict]:
    from photocull.sources import decode_image

    return decode_image(path, max_pixels)


class PhotoScanner:
    def discover(self, root: Path, cancelled=lambda: False):
        """Yield files/errors without following directory or file symlinks."""
        errors = []
        for folder, dirs, files in os.walk(root, followlinks=False, onerror=errors.append):
            if cancelled():
                return
            dirs.sort()
            for name in list(dirs):
                if (Path(folder) / name).is_symlink():
                    dirs.remove(name)
                    yield "symlink", Path(folder) / name
            for name in sorted(files):
                if cancelled():
                    return
                path = Path(folder) / name
                if path.is_symlink():
                    yield "symlink", path
                else:
                    yield "supported" if path.suffix.lower() in SUPPORTED else "unsupported", path
        for error in errors:
            yield "discovery_error", error

    def read(self, path: Path, max_pixels: int, full_hash: bool = True):
        from photocull.sources import FileImageSource

        return FileImageSource(path).read(max_pixels, full_hash)
