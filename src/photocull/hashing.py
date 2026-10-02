"""Deterministic 64-bit hashes; no grouping or recommendations."""

import cv2
import numpy as np
from PIL import Image

from photocull.provenance import image_runtime


def bits_hex(bits: np.ndarray) -> str:
    return f"{int(''.join('1' if v else '0' for v in bits.ravel()), 2):016x}"


class PerceptualHashService:
    name = "PerceptualHashService"
    version = "hashes_v1"
    parameters = {
        "bits": 64,
        "phash_edge": 32,
        "resize": "lanczos",
        "phash_dc": "excluded",
        "runtime": image_runtime(),
    }

    def analyze(self, image: Image.Image) -> dict:
        gray = image.convert("L")
        a = np.asarray(gray.resize((8, 8), Image.Resampling.LANCZOS), dtype=np.float32)
        d = np.asarray(gray.resize((9, 8), Image.Resampling.LANCZOS), dtype=np.float32)
        p = np.asarray(gray.resize((32, 32), Image.Resampling.LANCZOS), dtype=np.float32)
        low = cv2.dct(p)[:8, :8].copy()
        threshold = np.median(low.ravel()[1:])
        bits = low > threshold
        bits[0, 0] = False
        return {
            "ahash": bits_hex(a > a.mean()),
            "dhash": bits_hex(d[:, 1:] > d[:, :-1]),
            "phash": bits_hex(bits),
        }


def hamming(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()
