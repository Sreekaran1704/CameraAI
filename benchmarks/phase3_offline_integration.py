"""Real local model contract; run explicitly, not part of portable unit tests."""

import json
import socket
from pathlib import Path

import numpy as np
from PIL import Image

from photocull.cache import Cache
from photocull.embeddings import EmbeddingService


def deny(*args, **kwargs):
    raise AssertionError("Network forbidden during real local model inference")


socket.socket.connect = deny
socket.socket.connect_ex = deny
socket.create_connection = deny
cache = Cache(Path(__file__).resolve().parents[1] / ".photocull")
results = {}
for model in ("mobilenet", "tinyclip"):
    service = EmbeddingService(cache, model)
    records = [
        (
            f"offline-{i}",
            f"phase3-real-integration-v2-{i}",
            lambda i=i: Image.new("RGB", (250 + i, 260), (40 + i * 30, 100, 70)),
        )
        for i in range(3)
    ]
    first, stats = service.encode(records)
    second, warm = service.encode(records)
    for key in first:
        assert first[key].shape == (service.spec.dimension,)
        assert abs(float(np.linalg.norm(first[key])) - 1) < 1e-5
        np.testing.assert_array_equal(first[key], second[key])
    assert warm["cache_hits"] == 3
    # A distinct provenance key verifies inference determinism across actual executions.
    repeated = [(key, fingerprint + "-repeat", loader) for key, fingerprint, loader in records]
    third, repeated_stats = service.encode(repeated)
    for key in first:
        np.testing.assert_allclose(first[key], third[key], atol=1e-6)
    results[model] = {"cold": stats, "warm": warm, "deterministic": True, "network_denied": True}
print(json.dumps(results, sort_keys=True))
