"""Ranking reads real caches with sockets denied; source SHA checked before and after."""

import hashlib
import json
import socket
from dataclasses import replace
from pathlib import Path

from photocull.config import Config
from photocull.pipeline import run_sync
from photocull.ranking import export_manifest
from photocull.ranking_service import prepare, recommend
from photocull.storage import Repository


def deny(*args, **kwargs):
    raise AssertionError("Outbound networking forbidden in Phase 5")


socket.socket.connect = deny
socket.socket.connect_ex = deny
socket.create_connection = deny
root = Path(__file__).resolve().parents[1]
folder = root / "benchmark-output" / "phase4-events-v2"
paths = sorted(folder.glob("*.png"))
before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
config = Config(cache_dir=root / ".photocull")
run = run_sync(folder, config)
assert run["failures"] == 0
repo = Repository(config.cache_dir / "metadata.db")
output = {"network_denied": True, "models": {}}
for model in ("disabled", "mobilenet", "tinyclip"):
    cfg = replace(config, ranking=replace(config.ranking, model=model))
    data = prepare(repo, run["run_id"], cfg)
    cold = recommend(repo, cfg, data)
    warm = recommend(repo, cfg, data)
    assert warm["cache_hit"]
    if model != "disabled":
        assert data["embedding_reuse"]["cache_hit_rate"] == 1
        assert not data["embedding_reuse"]["inference_performed"]
    chosen = {r["photo_id"] for r in warm["selected"]}
    assert all(len(chosen & set(g["members"])) <= 1 for g in data["groups"])
    names = {i: e["name"] for e in data["events"]["events"] for i in e["members"]}
    for format in ("json", "csv"):
        manifest = export_manifest(warm["selected"], data["rows"], names, data["decisions"], format)
        assert manifest
    output["models"][model] = {
        "ranking_seconds": cold["ranking_seconds"],
        "shortlist_seconds": cold["shortlist_seconds"],
        "cache_hit": warm["cache_hit"],
        "reuse": data["embedding_reuse"],
        "selected": len(warm["selected"]),
        "known_group_contamination": 0,
        "feature_source": warm["feature_source"],
    }
repo.close()
after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
assert before == after
output["originals_unchanged"] = len(paths)
print(json.dumps(output, allow_nan=False))
