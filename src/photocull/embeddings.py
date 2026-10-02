"""Optional local inference. Only setup_model can download weights."""

import hashlib
import importlib.metadata
import json
import os
import ssl
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from photocull.cache import refuse_symlinks
from photocull.config import parameter_hash


@dataclass(frozen=True)
class ModelSpec:
    id: str
    architecture: str
    dimension: int
    url: str
    preprocessing: str
    license: str


MODELS = {
    "mobilenet": ModelSpec(
        "mobilenet",
        "mobilenet_v3_small",
        576,
        "https://download.pytorch.org/models/mobilenet_v3_small-047dcff4.pth",
        "imagenet-resize256-center224-bilinear-v1",
        "Torchvision BSD-3-Clause; ImageNet dataset terms",
    ),
    "tinyclip": ModelSpec(
        "tinyclip",
        "TinyCLIP-ViT-8M-16-Text-3M",
        512,
        "https://github.com/wkcn/TinyCLIP-model-zoo/releases/download/checkpoints/TinyCLIP-ViT-8M-16-Text-3M-YFCC15M.pt",
        "clip-resize224-center224-bicubic-v1",
        "MIT",
    ),
}

CHECKSUMS = {
    "mobilenet": "047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f",
    "tinyclip": "3d9f86a556cd13acc1aa6cc18495a79ffd1f58b6f17a552400bdefd244c3a92c",
}

MIGRATION_3 = """
BEGIN IMMEDIATE;
CREATE TABLE embedding_records (
 cache_key TEXT PRIMARY KEY, photo_id INTEGER REFERENCES source_photos(id),
 fingerprint TEXT NOT NULL, model_id TEXT NOT NULL, checksum TEXT NOT NULL,
 preprocessing TEXT NOT NULL, analysis_id TEXT REFERENCES analysis_versions(id),
 path TEXT NOT NULL, dimension INTEGER NOT NULL, device TEXT NOT NULL,
 generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
PRAGMA user_version=3;
COMMIT;
"""


class ModelUnavailable(ValueError):
    pass


def file_checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def setup_model(cache, model_id):
    """Explicit network operation, with atomic publication and tensor-only loading later."""
    try:
        import truststore
    except ImportError as exc:
        raise ModelUnavailable(
            'Install optional dependencies first: pip install -e ".[embeddings]"'
        ) from exc

    spec = MODELS[model_id]
    path = refuse_symlinks(cache.root / "models" / f"{model_id}.pt")
    with cache.lock():
        descriptor, temporary = tempfile.mkstemp(suffix=".tmp", dir=path.parent)
        try:
            with (
                os.fdopen(descriptor, "wb") as output,
                urllib.request.urlopen(
                    spec.url, timeout=60, context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ) as source,
            ):
                while block := source.read(1024 * 1024):
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            digest = file_checksum(Path(temporary))
            if digest != CHECKSUMS[model_id]:
                raise ValueError("Official model checksum mismatch")
            os.replace(temporary, path)
            metadata = {**spec.__dict__, "sha256": digest, "weight_bytes": path.stat().st_size}
            meta_path = refuse_symlinks(path.with_suffix(".json"))
            meta_path.write_text(json.dumps(metadata, indent=2))
            meta_path.chmod(0o600)
            return metadata
        finally:
            if Path(temporary).exists():
                Path(temporary).unlink()


def normalize(vectors):
    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    if not np.isfinite(vectors).all() or np.any(norms <= 1e-8):
        raise ValueError("Embedding must be finite and nonzero")
    return vectors / norms


def cosine(a, b):
    return float(np.clip(np.dot(normalize(a), normalize(b)), -1, 1))


def preprocess(image, model_id):
    image = ImageOps.exif_transpose(image).convert("RGB")
    edge = 224
    resize_edge = 256 if model_id == "mobilenet" else 224
    interpolation = (
        Image.Resampling.BILINEAR if model_id == "mobilenet" else Image.Resampling.BICUBIC
    )
    width, height = image.size
    shape = (
        (resize_edge, int(resize_edge * height / width))
        if width <= height
        else (int(resize_edge * width / height), resize_edge)
    )
    image = image.resize(shape, interpolation)
    x, y = round((image.width - edge) / 2), round((image.height - edge) / 2)
    array = (
        np.asarray(image.crop((x, y, x + edge, y + edge)), dtype=np.float32).transpose(2, 0, 1)
        / 255
    )
    if model_id == "mobilenet":
        array = (
            array - np.array([0.485, 0.456, 0.406], dtype=np.float32)[:, None, None]
        ) / np.array([0.229, 0.224, 0.225], dtype=np.float32)[:, None, None]
    else:
        array = (
            array - np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)[:, None, None]
        ) / np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)[:, None, None]
    return np.ascontiguousarray(array)


def select_device(torch, requested):
    return "mps" if requested in {"mps", "auto"} and torch.backends.mps.is_available() else "cpu"


class EmbeddingService:
    version = "embedding_service_v1"

    def __init__(self, cache, model_id, device="cpu", batch_size=16, repository=None, backend=None):
        self.cache, self.spec, self.repository = cache, MODELS[model_id], repository
        if not 1 <= batch_size <= 256:
            raise ValueError("Embedding batch size must be within 1..256")
        self.batch_size, self.backend, self.model = batch_size, backend, None
        self.requested_device, self.device, self.startup_seconds = device, "cpu", 0.0
        path = refuse_symlinks(cache.root / "models" / f"{model_id}.pt")
        if not path.is_file():
            raise ModelUnavailable(
                f"Local {model_id} model is not installed. Run: "
                f"photocull --cache-dir {cache.root} model-setup {model_id}"
            )
        self.path, self.checksum = path, file_checksum(path)
        if backend is None and self.checksum != CHECKSUMS[model_id]:
            raise ModelUnavailable("Unrecognized checkpoint; reinstall using model-setup")
        meta = refuse_symlinks(path.with_suffix(".json"))
        try:
            metadata = json.loads(meta.read_text()) if meta.is_file() else {}
        except (OSError, ValueError) as exc:
            raise ModelUnavailable(
                "Unreadable local model manifest; reinstall using model-setup"
            ) from exc
        if metadata.get("sha256") != self.checksum:
            raise ModelUnavailable("Local weight checksum mismatch; reinstall using model-setup")
        runtime = {name: importlib.metadata.version(name) for name in ("numpy", "Pillow")}
        if backend is None:
            try:
                runtime.update(
                    {
                        name: importlib.metadata.version(name)
                        for name in ("torch", "torchvision", "open-clip-torch")
                    }
                )
            except importlib.metadata.PackageNotFoundError as exc:
                raise ModelUnavailable(
                    'Install optional dependencies: pip install -e ".[embeddings]"'
                ) from exc
        self.identity = {
            "model_id": model_id,
            "checksum": self.checksum,
            "preprocessing": self.spec.preprocessing,
            "service_version": self.version,
            "runtime": runtime,
            "requested_device": device,
        }
        self.analysis_id = (
            repository.version("EmbeddingService", self.version, self.identity)
            if repository
            else None
        )

    def _load(self):
        if self.backend is not None or self.model is not None:
            return
        started = time.perf_counter()
        import torch

        torch.set_num_threads(4)
        self.device = select_device(torch, self.requested_device)
        if self.spec.id == "mobilenet":
            from torchvision.models import mobilenet_v3_small

            model = mobilenet_v3_small(weights=None)
            model.load_state_dict(torch.load(self.path, map_location="cpu", weights_only=True))
            model.classifier = torch.nn.Identity()
        else:
            import open_clip

            model = open_clip.CLIP(
                embed_dim=512,
                vision_cfg={"image_size": 224, "layers": 10, "width": 256, "patch_size": 16},
                text_cfg={
                    "context_length": 77,
                    "vocab_size": 49408,
                    "width": 256,
                    "heads": 4,
                    "layers": 3,
                },
            )
            state = torch.load(self.path, map_location="cpu", weights_only=True)
            state = state.get("state_dict", state)
            # Author release stores independently wrapped image/text encoders.
            prefix = "_image_encoder.module.visual."
            visual = {
                key.removeprefix(prefix): value
                for key, value in state.items()
                if key.startswith(prefix)
            }
            model.visual.load_state_dict(visual)
            model = model.visual
        model.eval().requires_grad_(False)
        try:
            self.model = model.to(self.device)
        except RuntimeError:
            if self.device != "mps":
                raise
            self.device = "cpu"
            self.model = model.to("cpu")
        self.startup_seconds = time.perf_counter() - started

    def encode(self, records, cancelled=lambda: False):
        """Records: (id, fingerprint, image loader). Loaders own source validation."""
        started = time.perf_counter()
        startup_before = self.startup_seconds
        output, misses, hits = {}, [], 0
        for identifier, fingerprint, loader in records:
            key = parameter_hash({"fingerprint": fingerprint, **self.identity})
            path = refuse_symlinks(self.cache.root / "embeddings" / f"{key}.npy")
            if path.is_file():
                try:
                    vector = np.load(path, allow_pickle=False)
                    if (
                        vector.shape != (self.spec.dimension,)
                        or not np.isfinite(vector).all()
                        or abs(float(np.linalg.norm(vector)) - 1) > 1e-4
                    ):
                        raise ValueError("Invalid cached embedding")
                    output[identifier] = vector
                    hits += 1
                    continue
                except (ValueError, OSError):
                    pass
            misses.append((identifier, fingerprint, loader, key, path))
        inference = 0.0
        if misses:
            try:
                self._load()
            except (ImportError, RuntimeError, OSError, ValueError) as exc:
                raise ModelUnavailable(
                    "Local model cannot load; reinstall optional dependencies "
                    "and run model-setup. Hash-only analysis can continue."
                ) from exc
        for start in range(0, len(misses), self.batch_size):
            if cancelled():
                raise InterruptedError("Embedding generation cancelled")
            batch = misses[start : start + self.batch_size]
            arrays = []
            for _, _, loader, _, _ in batch:
                image = loader()
                try:
                    arrays.append(preprocess(image, self.spec.id))
                finally:
                    image.close()
            tick = time.perf_counter()
            if self.backend:
                vectors = self.backend(np.stack(arrays))
            else:
                import torch

                with torch.inference_mode():
                    tensor = torch.from_numpy(np.stack(arrays)).to(self.device)
                    try:
                        vectors = self.model(tensor).cpu().numpy()
                    except RuntimeError:
                        if self.device != "mps":
                            raise
                        self.device = "cpu"
                        self.model.to("cpu")
                        vectors = self.model(tensor.cpu()).cpu().numpy()
            inference += time.perf_counter() - tick
            vectors = normalize(vectors)
            if vectors.shape != (len(batch), self.spec.dimension):
                raise ValueError("Model returned unexpected embedding dimensions")
            for (identifier, fingerprint, _, key, path), vector in zip(batch, vectors, strict=True):
                descriptor, temporary = tempfile.mkstemp(suffix=".tmp", dir=path.parent)
                try:
                    with os.fdopen(descriptor, "wb") as stream:
                        np.save(stream, vector, allow_pickle=False)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, path)
                finally:
                    if Path(temporary).exists():
                        Path(temporary).unlink()
                output[identifier] = vector
                if self.repository:
                    with self.repository.db:
                        self.repository.db.execute(
                            "INSERT OR REPLACE INTO embedding_records("
                            "cache_key,photo_id,fingerprint,"
                            "model_id,checksum,preprocessing,analysis_id,path,dimension,device) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (
                                key,
                                int(identifier),
                                fingerprint,
                                self.spec.id,
                                self.checksum,
                                self.spec.preprocessing,
                                self.analysis_id,
                                str(path),
                                self.spec.dimension,
                                self.device,
                            ),
                        )
        return output, {
            "model": self.spec.id,
            "checksum": self.checksum,
            "preprocessing": self.spec.preprocessing,
            "device": self.device if misses else f"cached ({self.requested_device})",
            "requested_device": self.requested_device,
            "batch_size": self.batch_size,
            "startup_seconds": self.startup_seconds - startup_before,
            "inference_seconds": inference,
            "total_seconds": time.perf_counter() - started,
            "images_per_second": len(misses) / inference if inference else None,
            "cache_hits": hits,
            "cache_hit_rate": hits / len(records) if records else 0,
            "generated": len(misses),
            "embedding_bytes": sum(v.nbytes for v in output.values()),
        }


def model_status(cache):
    """Installed/checksum status without loading torch or performing network operations."""
    from functools import lru_cache

    @lru_cache(maxsize=8)
    def digest(path, size, modified):
        return file_checksum(Path(path))

    # Retain only checksum strings across UI reruns, never checkpoint tensors.
    if not hasattr(model_status, "_digest"):
        model_status._digest = digest
    result = {}
    for identifier in MODELS:
        try:
            path = refuse_symlinks(cache.root / "models" / f"{identifier}.pt")
            stat = path.stat()
            valid = (
                model_status._digest(str(path), stat.st_size, stat.st_mtime_ns)
                == CHECKSUMS[identifier]
            )
            result[identifier] = {
                "installed": valid,
                "status": "Checksum verified" if valid else "Checksum mismatch; setup required",
                "checkpoint_sha256": CHECKSUMS[identifier],
            }
        except OSError:
            result[identifier] = {"installed": False, "status": "Not installed"}
        except ValueError:
            result[identifier] = {"installed": False, "status": "Unsafe model path; setup required"}
    return result
