"""CPU ranking scale with real cached source features repeated into larger metadata collections."""

import json
import resource
import socket
import sys
from dataclasses import replace
from pathlib import Path

from photocull.config import Config
from photocull.ranking import rank, shortlist
from photocull.ranking_service import prepare
from photocull.storage import Repository


def deny(*args, **kwargs):
    raise AssertionError("No inference/network allowed in ranking benchmark")


socket.socket.connect = deny
socket.create_connection = deny
root = Path(__file__).resolve().parents[1]
config = Config(cache_dir=root / ".photocull")
config = replace(config, ranking=replace(config.ranking, model="tinyclip"))
repo = Repository(config.cache_dir / "metadata.db")
scan = repo.runs()[0]["id"]
data = prepare(repo, scan, config)
assert data["embedding_reuse"]["cache_hit_rate"] == 1
rows = []
for size in (30, 100, 500, 1000, 5000):
    photos, vectors = [], {}
    for index in range(size):
        original = data["photos"][index % len(data["photos"])]
        identifier = f"scale-{index:05d}"
        photos.append(replace(original, id=identifier))
        vectors[identifier] = data["vectors"][original.id]
    for features in ("hash", "cached_tinyclip"):
        selected_vectors = vectors if features == "cached_tinyclip" else {}
        ranked = rank(photos, config.ranking, vectors=selected_vectors)
        selected = shortlist(
            photos, ranked["ranked"], min(20, size), config.ranking, selected_vectors
        )
        rows.append(
            {
                "records": size,
                "features": features,
                "ranking_seconds": ranked["ranking_seconds"],
                "shortlist_seconds": selected["shortlist_seconds"],
                "candidate_count": size,
                "comparisons": ranked["comparisons"] + selected["selection_comparisons"],
                "peak_memory_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                / (2**20 if sys.platform == "darwin" else 1024),
                "cache_hit_rate": 1 if selected_vectors else None,
            }
        )
repo.close()
print(
    json.dumps(
        {
            "measurements": rows,
            "unique_source_records": len(data["photos"]),
            "scope": (
                "Real 512D cached vectors/quality, cyclic metadata repeats at scale; "
                "no new photo inference"
            ),
            "network_denied": True,
        },
        allow_nan=False,
    )
)
