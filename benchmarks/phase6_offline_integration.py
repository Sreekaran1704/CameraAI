"""Network-denied current scan smoke and isolated model persistence/performance."""

import hashlib
import json
import socket
import tempfile
import time
from pathlib import Path

import numpy as np

from photocull.config import Config
from photocull.preference_storage import PreferenceStore
from photocull.preferences import candidates, feature_records, personalized, train
from photocull.ranking import VERSION as FROZEN_VERSION
from photocull.ranking_service import prepare
from photocull.storage import Repository

ROOT = Path(__file__).resolve().parent.parent


def deny(*args, **kwargs):
    raise RuntimeError("Network forbidden")


socket.socket.connect = deny
socket.socket.connect_ex = deny
socket.create_connection = deny

config = Config(cache_dir=ROOT / ".photocull")
repo = Repository(config.cache_dir / "metadata.db")
run = next(r for r in repo.runs() if r["status"] == "completed")
data = prepare(repo, run["id"], config)
sources = [Path(r["path"]) for r in data["rows"].values()]
before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
records = feature_records(data)
state = {}
store = PreferenceStore(state=state)
store.allocate(records)
pairs = candidates(data, records)
pair = pairs[0]
store.save(records[pair["a"]], records[pair["b"]], "tie")
model = store.model(records)
result = personalized(data, config, model, records, k=20)
assert not result["personalization_active"] and model["training_comparisons"] == 0
store.reset()
assert not store.feedback()
assert len(result["selected"]) == 20
ids = {r["photo_id"] for r in result["selected"]}
assert all(len(ids & set(g["members"])) <= 1 for g in data["groups"])
assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
repo.close()

# Pure metadata simulator, isolated from the real user's preference database.
rng = np.random.default_rng(170406)
training_records, examples = {}, []
for group in range(32):
    rows = []
    for index in range(4):
        x = rng.normal(0, 0.08, 15)
        x[1] = index / 3
        identifier = f"sim-{group}-{index}"
        r = dict(
            photo_id=identifier,
            fingerprint=identifier,
            source_versions={},
            x=x.tolist(),
            a=1 - x[1],
            b=1 - x[1],
            group=f"sim-group-{group}",
            context=f"sim-{group}",
            partition="train" if group < 24 else "holdout",
            feature_source="perceptual_hash_surrogate",
        )
        rows.append(r)
        training_records[identifier] = r
    for a in range(4):
        for b in range(a + 1, 4):
            examples.append(
                dict(
                    a=rows[a],
                    b=rows[b],
                    choice="b",
                    group=rows[a]["group"],
                    partition=rows[a]["partition"],
                    repeat=False,
                    pair_key=f"{rows[a]['photo_id']}|{rows[b]['photo_id']}",
                )
            )
started = time.perf_counter()
trained = train(examples)
full_fit = time.perf_counter() - started
assert trained["active"]
with tempfile.TemporaryDirectory(dir="/private/tmp", prefix="photocull-preference-") as folder:
    db_path = Path(folder) / "preferences.db"
    isolated = Repository(db_path)
    isolated.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    empty_database_bytes = db_path.stat().st_size
    persistent = PreferenceStore(isolated)
    persistent.allocate(training_records)
    for e in examples:
        persistent.save(
            training_records[e["a"]["photo_id"]], training_records[e["b"]["photo_id"]], e["choice"]
        )
    started = time.perf_counter()
    persisted = persistent.model(training_records)
    persist_seconds = time.perf_counter() - started
    assert persisted["active"]
    isolated.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    database_bytes = db_path.stat().st_size
    model_bytes = len(json.dumps(persisted).encode())
    isolated.close()
    reopened = Repository(db_path)
    started = time.perf_counter()
    loaded = PreferenceStore(reopened).model(training_records)
    reload_seconds = time.perf_counter() - started
    assert loaded["coefficients"] == persisted["coefficients"]
    PreferenceStore(reopened).reset()
    assert not PreferenceStore(reopened).feedback()
    reopened.close()

payload = {
    "network_denied": True,
    "photos_checked": len(sources),
    "originals_unchanged": len(sources),
    "frozen_ranking_version": FROZEN_VERSION,
    "local_human_feedback_written": 0,
    "session_only_tie_reset": True,
    "generic_fallback": True,
    "known_group_contamination": 0,
    "candidate_pairs": len(pairs),
    "full_train_tune_bootstrap_seconds_144": full_fit,
    "model_fit_persist_seconds_192_feedback": persist_seconds,
    "model_reload_seconds": reload_seconds,
    "model_json_bytes": model_bytes,
    "isolated_database_bytes_192_feedback": database_bytes,
    "empty_schema_database_bytes": empty_database_bytes,
    "incremental_preference_bytes": database_bytes - empty_database_bytes,
    "isolated_database_includes_schema_overhead": True,
}
(ROOT / "benchmarks/phase6-offline-integration.json").write_text(
    json.dumps(payload, indent=2) + "\n"
)
print(json.dumps(payload, indent=2))
