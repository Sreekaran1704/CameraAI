"""Real-model event execution with sockets blocked and originals hash-checked."""

import hashlib
import json
import socket
from dataclasses import replace
from pathlib import Path

from photocull.cache import Cache
from photocull.config import Config, EventConfig
from photocull.events import discover_for_scan
from photocull.pipeline import run_sync
from photocull.storage import Repository


def deny(*args, **kwargs):
    raise AssertionError("Outbound network forbidden during Phase 4")


socket.socket.connect = deny
socket.socket.connect_ex = deny
socket.create_connection = deny
root = Path(__file__).resolve().parents[1]
folder = root / "benchmark-output" / "phase4-events-v2"
cache = Cache(root / ".photocull")
paths = sorted(folder.glob("*.png"))
before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
config = Config(cache_dir=cache.root)
baseline = run_sync(folder, config)
assert baseline["failures"] == 0
assert baseline["events"]["parameters"]["method"] == "time"
repo = Repository(cache.root / "metadata.db")
output = {"baseline": baseline["events"], "models": {}, "network_denied": True}
evaluation = json.loads((root / "benchmarks" / "phase4-event-evaluation.json").read_text())
for finalist in evaluation["finalists"][1:]:
    cfg = replace(config, events=EventConfig(**finalist["parameters"]))
    cold = discover_for_scan(repo, baseline["run_id"], cfg)
    warm = discover_for_scan(repo, baseline["run_id"], cfg)
    assert warm["cache_hit"]
    assert warm["embeddings"]["cache_hits"] == len(paths)
    assert cfg.embeddings.model == "disabled"
    output["models"][finalist["model"]] = {
        "event_count": cold["event_count"],
        "unassigned_count": cold["unassigned_count"],
        "cold": cold["embeddings"],
        "warm": warm["embeddings"],
        "cache_hit": warm["cache_hit"],
    }
# Restore the selected default automatic snapshot for the UI/history.
discover_for_scan(repo, baseline["run_id"], config)
repo.close()
after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
assert before == after
output["originals_unchanged"] = len(paths)
print(json.dumps(output, allow_nan=False))
