"""Atomic orientation-correct previews outside original folders."""

import io
import os
import tempfile

from PIL import Image

from photocull.cache import Cache, refuse_symlinks
from photocull.config import parameter_hash
from photocull.provenance import image_runtime


def thumbnail_bytes(image, edge=512, quality=85):
    """Shared bounded JPEG preview encoder. No file operations."""
    small = image.copy()
    try:
        small.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        with io.BytesIO() as stream:
            small.save(stream, format="JPEG", quality=quality)
            return stream.getvalue(), small.width, small.height
    finally:
        small.close()


class ThumbnailService:
    name = "ThumbnailService"
    version = "thumbnail_v1"

    def __init__(self, cache: Cache, edge: int, quality: int):
        self.cache = cache
        self.parameters = {
            "edge": edge,
            "quality": quality,
            "format": "JPEG",
            "resize": "lanczos",
            "orientation": "exif_transpose",
            "runtime": image_runtime(),
        }

    def key(self, fingerprint: str) -> str:
        return parameter_hash(
            {"source": fingerprint, "version": self.version, "parameters": self.parameters}
        )

    def generate(self, image: Image.Image, fingerprint: str):
        destination = refuse_symlinks(
            self.cache.root / "thumbnails" / f"{self.key(fingerprint)}.jpg"
        )
        encoded, width, height = thumbnail_bytes(
            image, self.parameters["edge"], self.parameters["quality"]
        )
        descriptor, temporary = tempfile.mkstemp(suffix=".tmp", dir=destination.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {
            "path": str(destination),
            "width": width,
            "height": height,
            "cache_key": self.key(fingerprint),
        }
