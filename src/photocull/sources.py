"""Decoded-image sources shared by disk and upload orchestration; no Streamlit types."""

import hashlib
import io
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

FORMATS = {"JPEG", "PNG", "WEBP"}
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def decode_image(source, max_pixels, decode_edge=None):
    """Verify header before allocating pixels; return only whitelisted EXIF fields."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(source) as image:
            if image.format not in FORMATS:
                raise ValueError("Use JPEG, PNG or WEBP images.")
            if image.width * image.height > max_pixels:
                raise ValueError(
                    f"Image exceeds the configured pixel limit ({max_pixels / 1e6:g} megapixels)."
                )
            image.verify()
        if hasattr(source, "seek"):
            source.seek(0)
        with Image.open(source) as original:
            exif = original.getexif()
            try:
                exif_ifd = exif.get_ifd(34665)
            except (KeyError, TypeError, ValueError):
                exif_ifd = {}
            capture = exif_ifd.get(36867, exif.get(36867))
            timezone = exif_ifd.get(36881, exif.get(36881))
            timestamp = None
            if capture:
                try:
                    timestamp = datetime.strptime(str(capture), "%Y:%m:%d %H:%M:%S").isoformat()
                except ValueError:
                    pass
            orientation = int(exif.get(274, 1))
            size = original.size
            # JPEG draft can reduce allocation; PNG still bounded by the verified pixel count.
            if decode_edge:
                original.draft("RGB", (decode_edge, decode_edge))
            image = ImageOps.exif_transpose(original).convert("RGB")
            image.load()
            if decode_edge:
                image.thumbnail((decode_edge, decode_edge), Image.Resampling.LANCZOS)
    width, height = size[::-1] if orientation in (5, 6, 7, 8) else size
    return image, {
        "orientation": orientation,
        "original_width": size[0],
        "original_height": size[1],
        "width": width,
        "height": height,
        "capture_time": timestamp,
        "capture_timezone": str(timezone)[:8] if timezone else None,
        "timestamp_provenance": "exif" if timestamp else "unknown",
    }


@dataclass(frozen=True)
class FileImageSource:
    path: Path

    def read(self, max_pixels, full_hash=True):
        from photocull.scanner import SourceChangedError, content_hash, fingerprint, load_image

        before = fingerprint(self.path)
        stat = self.path.stat()
        image, metadata = load_image(self.path, max_pixels)
        try:
            sha = content_hash(self.path) if full_hash else None
            if fingerprint(self.path) != before:
                raise SourceChangedError("Source changed during reading")
        except Exception:
            image.close()
            raise
        metadata.update(
            path=str(self.path.resolve()),
            filename=self.path.name,
            extension=self.path.suffix.lower(),
            file_size=stat.st_size,
            width=image.width,
            height=image.height,
            mtime_ns=stat.st_mtime_ns,
            ctime_ns=stat.st_ctime_ns,
            birthtime=getattr(stat, "st_birthtime", None),
            filesystem_time=datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
            timestamp_provenance="exif" if metadata["capture_time"] else "filesystem_mtime",
            fingerprint=before,
            content_sha256=sha,
        )
        return image, metadata


@dataclass(frozen=True)
class UploadedImageSource:
    name: str
    data: bytes | memoryview

    def read(self, max_pixels=8_000_000, decode_edge=2048):
        # Do not interpret submitted names as filesystem paths.
        filename = self.name.replace("\\", "/").split("/")[-1][:120]
        if Path(filename).suffix.lower() not in EXTENSIONS:
            raise ValueError("Use .jpg, .jpeg, .png or .webp files.")
        digest = hashlib.sha256(self.data).hexdigest()
        with io.BytesIO(self.data) as stream:
            image, metadata = decode_image(stream, max_pixels, decode_edge)
        metadata.update(
            filename=filename,
            path="session-upload",
            extension=Path(filename).suffix.lower(),
            file_size=len(self.data),
            fingerprint=digest,
            content_sha256=digest,
            filesystem_time=None,
        )
        return image, metadata
