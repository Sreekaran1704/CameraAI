"""Phase 2 migration, immutable detection runs and fingerprint-scoped corrections."""

import json
import uuid

from photocull.config import parameter_hash
from photocull.similarity import group_signature, pair_key
from photocull.storage import now

MIGRATION_2 = """
BEGIN IMMEDIATE;
CREATE TABLE duplicate_runs (
    id TEXT PRIMARY KEY, analysis_id TEXT NOT NULL REFERENCES analysis_versions(id),
    dataset_key TEXT NOT NULL, generated_at TEXT NOT NULL, summary_json TEXT NOT NULL,
    UNIQUE(analysis_id, dataset_key)
);
CREATE TABLE duplicate_scan_links (
    scan_id TEXT PRIMARY KEY REFERENCES scan_runs(id),
    duplicate_run_id TEXT NOT NULL REFERENCES duplicate_runs(id)
);
CREATE TABLE similarity_pairs (
    run_id TEXT NOT NULL REFERENCES duplicate_runs(id) ON DELETE CASCADE,
    a_id INTEGER NOT NULL REFERENCES source_photos(id),
    b_id INTEGER NOT NULL REFERENCES source_photos(id),
    a_fingerprint TEXT NOT NULL, b_fingerprint TEXT NOT NULL,
    relationship TEXT NOT NULL CHECK(relationship IN
      ('EXACT_DUPLICATE','NEAR_DUPLICATE','BURST_GROUP','VISUALLY_SIMILAR')),
    evidence_json TEXT NOT NULL, source_versions_json TEXT NOT NULL, generated_at TEXT NOT NULL,
    PRIMARY KEY(run_id,a_id,b_id)
);
CREATE TABLE duplicate_groups (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES duplicate_runs(id) ON DELETE CASCADE,
    relationship TEXT NOT NULL CHECK(relationship IN
      ('EXACT_DUPLICATE','NEAR_DUPLICATE','BURST_GROUP','VISUALLY_SIMILAR')),
    representative_id INTEGER NOT NULL REFERENCES source_photos(id),
    signature TEXT NOT NULL, evidence_json TEXT NOT NULL, generated_at TEXT NOT NULL
);
CREATE TABLE duplicate_members (
    group_id TEXT NOT NULL REFERENCES duplicate_groups(id) ON DELETE CASCADE,
    photo_id INTEGER NOT NULL REFERENCES source_photos(id), fingerprint TEXT NOT NULL,
    source_versions_json TEXT NOT NULL, membership_evidence_json TEXT NOT NULL,
    PRIMARY KEY(group_id,photo_id)
);
CREATE TABLE not_duplicate_pairs (
    a_id INTEGER NOT NULL REFERENCES source_photos(id),
    b_id INTEGER NOT NULL REFERENCES source_photos(id),
    a_fingerprint TEXT NOT NULL, b_fingerprint TEXT NOT NULL, generated_at TEXT NOT NULL,
    PRIMARY KEY(a_id,b_id,a_fingerprint,b_fingerprint)
);
CREATE TABLE not_duplicate_groups (
    signature TEXT PRIMARY KEY, members_json TEXT NOT NULL, generated_at TEXT NOT NULL
);
CREATE INDEX duplicate_group_run ON duplicate_groups(run_id);
PRAGMA user_version=2;
COMMIT;
"""


class DuplicateStore:
    def __init__(self, repository):
        self.repository = repository
        self.db = repository.db

    def corrections(self, photos):
        by_id = {p.id: p for p in photos}
        blocked = set()
        for row in self.db.execute("SELECT * FROM not_duplicate_pairs"):
            a, b = str(row["a_id"]), str(row["b_id"])
            if (
                a in by_id
                and b in by_id
                and by_id[a].fingerprint == row["a_fingerprint"]
                and by_id[b].fingerprint == row["b_fingerprint"]
            ):
                blocked.add(pair_key(a, b))
        suppressed = {r[0] for r in self.db.execute("SELECT signature FROM not_duplicate_groups")}
        return blocked, suppressed

    def dataset_key(self, photos, blocked, suppressed):
        return parameter_hash(
            {
                "photos": sorted(
                    (p.id, p.fingerprint, p.source_versions, p.storage_identity, p.link_count)
                    for p in photos
                ),
                "blocked": sorted(blocked),
                "suppressed": sorted(suppressed),
            }
        )

    def cached(self, analysis_id, dataset_key):
        row = self.db.execute(
            "SELECT id FROM duplicate_runs WHERE analysis_id=? AND dataset_key=?",
            (analysis_id, dataset_key),
        ).fetchone()
        return self.load(row[0]) if row else None

    def link(self, scan_id, duplicate_run_id):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO duplicate_scan_links VALUES (?,?)",
                (scan_id, duplicate_run_id),
            )

    def save(self, scan_id, analysis_id, dataset_key, result, photos):
        run_id = uuid.uuid4().hex
        by_id = {p.id: p for p in photos}
        timestamp = now()
        summary = {k: v for k, v in result.items() if k not in {"groups", "pairs"}}
        with self.db:
            self.db.execute(
                "INSERT INTO duplicate_runs VALUES (?,?,?,?,?)",
                (run_id, analysis_id, dataset_key, timestamp, json.dumps(summary)),
            )
            for pair in result["pairs"]:
                a, b = by_id[pair["a"]], by_id[pair["b"]]
                self.db.execute(
                    "INSERT OR REPLACE INTO similarity_pairs VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        run_id,
                        a.id,
                        b.id,
                        a.fingerprint,
                        b.fingerprint,
                        pair["relationship"],
                        json.dumps(pair),
                        json.dumps({a.id: a.source_versions, b.id: b.source_versions}),
                        timestamp,
                    ),
                )
            for group in result["groups"]:
                identifier = uuid.uuid4().hex
                self.db.execute(
                    "INSERT INTO duplicate_groups VALUES (?,?,?,?,?,?,?)",
                    (
                        identifier,
                        run_id,
                        group["type"],
                        group["representative"],
                        group["signature"],
                        json.dumps(group),
                        timestamp,
                    ),
                )
                for member in group["members"]:
                    photo = by_id[member]
                    # Store pair IDs rather than repeatedly copying all group evidence per member.
                    links = [
                        (p["a"], p["b"]) for p in group["evidence"] if member in (p["a"], p["b"])
                    ]
                    self.db.execute(
                        "INSERT INTO duplicate_members VALUES (?,?,?,?,?)",
                        (
                            identifier,
                            photo.id,
                            photo.fingerprint,
                            json.dumps(photo.source_versions),
                            json.dumps(links),
                        ),
                    )
        self.link(scan_id, run_id)
        return self.load(run_id)

    def load(self, run_id):
        row = self.db.execute("SELECT * FROM duplicate_runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            return None
        result = json.loads(row["summary_json"])
        result.update(
            {
                "duplicate_run_id": run_id,
                "analysis_id": row["analysis_id"],
                "generated_at": row["generated_at"],
                "groups": [],
                "pairs": [],
            }
        )
        for group in self.db.execute(
            "SELECT * FROM duplicate_groups WHERE run_id=? ORDER BY relationship,signature",
            (run_id,),
        ):
            result["groups"].append({**json.loads(group["evidence_json"]), "id": group["id"]})
        for pair in self.db.execute(
            "SELECT evidence_json FROM similarity_pairs WHERE run_id=?", (run_id,)
        ):
            result["pairs"].append(json.loads(pair[0]))
        return result

    def for_scan(self, scan_id):
        row = self.db.execute(
            "SELECT duplicate_run_id FROM duplicate_scan_links WHERE scan_id=?", (scan_id,)
        ).fetchone()
        return self.load(row[0]) if row else None

    def decide(self, photo_id, decision):
        if decision not in {"keep", "favorite", "review"}:
            raise ValueError("Unsupported Phase 2 decision")
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO user_decisions VALUES (?,?,?)", (photo_id, decision, now())
            )

    def not_duplicate(self, members, member_id=None):
        """Group correction scopes to membership; member correction blocks current peers."""
        with self.db:
            if member_id is None:
                self.db.execute(
                    "INSERT OR REPLACE INTO not_duplicate_groups VALUES (?,?,?)",
                    (
                        group_signature(members),
                        json.dumps([(p.id, p.fingerprint) for p in members]),
                        now(),
                    ),
                )
            else:
                selected = next(p for p in members if p.id == str(member_id))
                for other in members:
                    if other.id == selected.id:
                        continue
                    a, b = sorted((selected, other), key=lambda p: p.id)
                    self.db.execute(
                        "INSERT OR REPLACE INTO not_duplicate_pairs VALUES (?,?,?,?,?)",
                        (a.id, b.id, a.fingerprint, b.fingerprint, now()),
                    )
