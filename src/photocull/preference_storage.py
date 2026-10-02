"""Preference snapshots, revisions and model JSON. No pickle or image storage."""

import hashlib
import json

from photocull.preferences import FEATURE_VERSION, VERSION, pair_key, partition, train
from photocull.storage import now

MIGRATION_6 = """
BEGIN IMMEDIATE;
CREATE TABLE preference_feedback (
 id INTEGER PRIMARY KEY, pair_key TEXT NOT NULL, a_json TEXT NOT NULL, b_json TEXT NOT NULL,
 choice TEXT NOT NULL CHECK(choice IN ('a','b','tie','skip')),
 group_id TEXT NOT NULL, partition TEXT NOT NULL CHECK(partition IN ('train','holdout')),
 repeat INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE preference_revisions (
 id INTEGER PRIMARY KEY, feedback_id INTEGER NOT NULL,
 previous_choice TEXT, action TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE preference_models (
 id INTEGER PRIMARY KEY, version TEXT NOT NULL, feature_version TEXT NOT NULL,
 training_hash TEXT NOT NULL UNIQUE, model_json TEXT NOT NULL, trained_at TEXT NOT NULL
);
CREATE TABLE preference_partitions (
 photo_id TEXT NOT NULL, fingerprint TEXT NOT NULL, partition TEXT NOT NULL,
 group_id TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(photo_id,fingerprint)
);
PRAGMA user_version=6;
COMMIT;
"""


class PreferenceStore:
    def __init__(self, repo=None, state=None):
        """None repository means isolated session-only Web Demo state."""
        self.repo = repo
        self.state = state if state is not None else {}
        self.state.setdefault("feedback", [])
        self.state.setdefault("revisions", [])
        self.state.setdefault("partitions", {})
        self.state.setdefault("model", {})

    def feedback(self):
        if self.repo:
            rows = [
                dict(r)
                for r in self.repo.db.execute("SELECT * FROM preference_feedback ORDER BY id")
            ]
            return [
                dict(r, a=json.loads(r["a_json"]), b=json.loads(r["b_json"]), group=r["group_id"])
                for r in rows
            ]
        return [dict(r) for r in self.state["feedback"]]

    def allocate(self, records):
        """Sticky allocations; merging train/holdout components quarantines ALL as holdout."""
        if self.repo:
            ledger = {
                (r["photo_id"], r["fingerprint"]): (r["partition"], r["group_id"])
                for r in self.repo.db.execute("SELECT * FROM preference_partitions")
            }
        else:
            ledger = self.state["partitions"]
        groups = {}
        for r in records.values():
            groups.setdefault(r["group"], []).append(r)
        # Preserve historical feedback connectivity even after manual event splitting.
        parent = {g: g for g in groups}

        def root(g):
            while parent[g] != g:
                parent[g] = parent[parent[g]]
                g = parent[g]
            return g

        historic = {}
        for r in records.values():
            previous = ledger.get((r["photo_id"], r["fingerprint"]))
            if previous and previous[1]:
                g = root(r["group"])
                if previous[1] in historic:
                    old_root = root(historic[previous[1]])
                    parent[max(g, old_root)] = min(g, old_root)
                historic[previous[1]] = root(g)
        for e in self.feedback():
            a, b = records.get(e["a"]["photo_id"]), records.get(e["b"]["photo_id"])
            if (
                a
                and b
                and a["fingerprint"] == e["a"]["fingerprint"]
                and b["fingerprint"] == e["b"]["fingerprint"]
            ):
                ga, gb = root(a["group"]), root(b["group"])
                parent[max(ga, gb)] = min(ga, gb)
        components = {}
        for g, rs in groups.items():
            components.setdefault(root(g), []).extend(rs)
        for rs in components.values():
            g = hashlib.sha256("|".join(sorted(r["photo_id"] for r in rs)).encode()).hexdigest()
            old = {
                ledger[(r["photo_id"], r["fingerprint"])][0]
                for r in rs
                if (r["photo_id"], r["fingerprint"]) in ledger
            }
            allocation = "holdout" if "holdout" in old else "train" if old else partition(g)
            for r in rs:
                r["group"], r["partition"] = g, allocation
                ledger[(r["photo_id"], r["fingerprint"])] = (allocation, g)
        if self.repo:
            with self.repo.db:
                self.repo.db.executemany(
                    "INSERT OR REPLACE INTO preference_partitions VALUES (?,?,?,?)",
                    [(i, fp, p, g) for (i, fp), (p, g) in ledger.items()],
                )
        else:
            self.state["partitions"] = ledger
        return records

    def save(self, a, b, choice, repeat=False):
        if choice not in {"a", "b", "tie", "skip"}:
            raise ValueError("Unknown preference choice")
        if a["photo_id"] == b["photo_id"] or a["group"] != b["group"]:
            raise ValueError("Pairs must contain distinct photos in the same connected group")
        key = pair_key(a["photo_id"], b["photo_id"])
        if not repeat and any(
            e["pair_key"] == key
            and {e["a"]["fingerprint"], e["b"]["fingerprint"]}
            == {a["fingerprint"], b["fingerprint"]}
            for e in self.feedback()
        ):
            raise ValueError("Pair already compared; correct feedback or explicitly repeat")
        timestamp = now()
        allocation = a.get("partition", partition(a["group"]))
        if allocation != b.get("partition", partition(b["group"])):
            raise ValueError("Cross-partition comparison refused")
        if self.repo:
            with self.repo.db:
                cursor = self.repo.db.execute(
                    "INSERT INTO preference_feedback(pair_key,a_json,b_json,choice,"
                    "group_id,partition,"
                    "repeat,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        key,
                        json.dumps(a),
                        json.dumps(b),
                        choice,
                        a["group"],
                        allocation,
                        int(repeat),
                        timestamp,
                        timestamp,
                    ),
                )
                identifier = cursor.lastrowid
                self.repo.db.execute(
                    "INSERT INTO preference_revisions(feedback_id,action,created_at) "
                    "VALUES (?,'create',?)",
                    (identifier, timestamp),
                )
                self.repo.db.execute("DELETE FROM preference_models")
        else:
            identifier = max((e["id"] for e in self.feedback()), default=0) + 1
            self.state["feedback"].append(
                dict(
                    id=identifier,
                    pair_key=key,
                    a=a,
                    b=b,
                    choice=choice,
                    group=a["group"],
                    partition=allocation,
                    repeat=repeat,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
            self.state["revisions"].append(dict(feedback_id=identifier, action="create"))
            self.state["model"] = {}
        return identifier

    def correct(self, identifier, choice):
        if choice not in {"a", "b", "tie", "skip"}:
            raise ValueError("Unknown preference choice")
        entry = next((e for e in self.feedback() if e["id"] == identifier), None)
        if not entry:
            raise ValueError("Unknown feedback")
        if self.repo:
            with self.repo.db:
                self.repo.db.execute(
                    "INSERT INTO preference_revisions(feedback_id,previous_choice,"
                    "action,created_at) "
                    "VALUES (?,?,'correct',?)",
                    (identifier, entry["choice"], now()),
                )
                self.repo.db.execute(
                    "UPDATE preference_feedback SET choice=?,updated_at=? WHERE id=?",
                    (choice, now(), identifier),
                )
                self.repo.db.execute("DELETE FROM preference_models")
        else:
            self.state["revisions"].append(
                dict(feedback_id=identifier, previous_choice=entry["choice"], action="correct")
            )
            next(e for e in self.state["feedback"] if e["id"] == identifier)["choice"] = choice
            self.state["model"] = {}

    def undo(self):
        if self.repo:
            revision = self.repo.db.execute(
                "SELECT * FROM preference_revisions ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not revision:
                return False
            with self.repo.db:
                if revision["action"] == "create":
                    self.repo.db.execute(
                        "DELETE FROM preference_feedback WHERE id=?", (revision["feedback_id"],)
                    )
                else:
                    self.repo.db.execute(
                        "UPDATE preference_feedback SET choice=? WHERE id=?",
                        (revision["previous_choice"], revision["feedback_id"]),
                    )
                self.repo.db.execute(
                    "DELETE FROM preference_revisions WHERE id=?", (revision["id"],)
                )
                self.repo.db.execute("DELETE FROM preference_models")
        else:
            if not self.state["revisions"]:
                return False
            r = self.state["revisions"].pop()
            if r["action"] == "create":
                self.state["feedback"] = [e for e in self.feedback() if e["id"] != r["feedback_id"]]
            else:
                next(e for e in self.state["feedback"] if e["id"] == r["feedback_id"])["choice"] = (
                    r["previous_choice"]
                )
            self.state["model"] = {}
        return True

    def examples(self, records):
        self.allocate(records)
        examples = []
        for e in self.feedback():
            a, b = records.get(e["a"]["photo_id"]), records.get(e["b"]["photo_id"])
            if not a or not b:
                continue
            # Changed sources or analysis feature versions cannot silently reuse stale labels.
            if any(
                current["fingerprint"] != old["fingerprint"]
                or current.get("source_versions") != old.get("source_versions")
                or current["x"] != old["x"]
                or current["feature_source"] != old["feature_source"]
                for current, old in ((a, e["a"]), (b, e["b"]))
            ):
                continue
            examples.append(dict(e, a=a, b=b, group=a["group"], partition=a["partition"]))
        return examples

    def model(self, records):
        examples = self.examples(records)
        identity = hashlib.sha256(
            json.dumps(
                {"version": VERSION, "features": FEATURE_VERSION, "examples": examples},
                sort_keys=True,
            ).encode()
        ).hexdigest()
        if self.repo:
            row = self.repo.db.execute(
                "SELECT model_json FROM preference_models WHERE training_hash=?", (identity,)
            ).fetchone()
            if row:
                return json.loads(row[0])
        elif self.state["model"].get("training_hash") == identity:
            return self.state["model"]
        model = train(examples)
        model.update(
            training_hash=identity,
            trained_at=now(),
            version=VERSION,
            feature_version=FEATURE_VERSION,
            excluded_stale_feedback=len(self.feedback()) - len(examples),
        )
        if self.repo:
            with self.repo.db:
                self.repo.db.execute(
                    "INSERT OR REPLACE INTO preference_models"
                    "(version,feature_version,training_hash,model_json,trained_at)"
                    "VALUES (?,?,?,?,?)",
                    (VERSION, FEATURE_VERSION, identity, json.dumps(model), now()),
                )
        else:
            self.state["model"] = model
        return model

    def reset(self):
        if self.repo:
            with self.repo.db:
                for table in (
                    "preference_models",
                    "preference_feedback",
                    "preference_revisions",
                    "preference_partitions",
                ):
                    self.repo.db.execute(f"DELETE FROM {table}")
        else:
            self.state.update(feedback=[], revisions=[], partitions={}, model={})
        if self.repo:
            self.repo.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.repo.db.execute("VACUUM")


def consistency(examples):
    originals, agreement = {}, []
    for e in examples:
        if e["choice"] not in {"a", "b", "tie"}:
            continue
        # Canonical winner makes agreement independent of displayed side.
        winner = "tie" if e["choice"] == "tie" else e[e["choice"]]["photo_id"]
        key = e["pair_key"]
        if e.get("repeat") and key in originals:
            agreement.append(winner == originals[key])
        elif not e.get("repeat"):
            originals[key] = winner
    return {
        "repeated_comparisons": len(agreement),
        "agreement": sum(agreement) / len(agreement) if agreement else None,
    }
