"""SQLite migrations and short transactional writes. JSON is derived metadata only."""

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from photocull import __version__
from photocull.cache import refuse_symlinks
from photocull.config import parameter_hash


def now() -> str:
    return datetime.now(UTC).isoformat()


MIGRATION_1 = """
BEGIN IMMEDIATE;
CREATE TABLE source_photos (
    id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL,
    content_sha256 TEXT, metadata_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE scan_runs (
    id TEXT PRIMARY KEY, source_root TEXT NOT NULL, mode TEXT NOT NULL,
    status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
    app_version TEXT NOT NULL, config_json TEXT NOT NULL,
    progress_json TEXT NOT NULL DEFAULT '{}', cancel_requested INTEGER NOT NULL DEFAULT 0,
    worker_pid INTEGER, worker_token TEXT
);
CREATE TABLE run_photos (
    run_id TEXT NOT NULL REFERENCES scan_runs(id),
    photo_id INTEGER NOT NULL REFERENCES source_photos(id), fingerprint TEXT NOT NULL,
    PRIMARY KEY(run_id, photo_id)
);
CREATE TABLE analysis_versions (
    id TEXT PRIMARY KEY, component TEXT NOT NULL, algorithm_version TEXT NOT NULL,
    parameter_hash TEXT NOT NULL, parameters_json TEXT NOT NULL,
    UNIQUE(component, algorithm_version, parameter_hash)
);
CREATE TABLE quality_measurements (
    photo_id INTEGER NOT NULL REFERENCES source_photos(id), fingerprint TEXT NOT NULL,
    analysis_id TEXT NOT NULL REFERENCES analysis_versions(id), generated_at TEXT NOT NULL,
    raw_json TEXT NOT NULL, normalized_json TEXT NOT NULL, warnings_json TEXT NOT NULL,
    technical_quality_v1 REAL NOT NULL, PRIMARY KEY(photo_id, fingerprint, analysis_id)
);
CREATE TABLE perceptual_hashes (
    photo_id INTEGER NOT NULL REFERENCES source_photos(id), fingerprint TEXT NOT NULL,
    analysis_id TEXT NOT NULL REFERENCES analysis_versions(id), generated_at TEXT NOT NULL,
    phash TEXT NOT NULL, dhash TEXT NOT NULL, ahash TEXT NOT NULL,
    PRIMARY KEY(photo_id, fingerprint, analysis_id)
);
CREATE TABLE thumbnail_metadata (
    photo_id INTEGER NOT NULL REFERENCES source_photos(id), fingerprint TEXT NOT NULL,
    analysis_id TEXT NOT NULL REFERENCES analysis_versions(id), generated_at TEXT NOT NULL,
    path TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL, cache_key TEXT NOT NULL,
    PRIMARY KEY(photo_id, fingerprint, analysis_id)
);
CREATE TABLE processing_failures (
    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES scan_runs(id),
    path TEXT, stage TEXT NOT NULL, error_type TEXT NOT NULL, message TEXT NOT NULL,
    generated_at TEXT NOT NULL
);
CREATE TABLE user_decisions (
    photo_id INTEGER PRIMARY KEY REFERENCES source_photos(id),
    decision TEXT NOT NULL CHECK(decision IN ('favorite','keep','review','reject')),
    updated_at TEXT NOT NULL
);
CREATE INDEX run_photos_run ON run_photos(run_id);
CREATE INDEX failures_run ON processing_failures(run_id);
PRAGMA user_version=1;
COMMIT;
"""


class Repository:
    def __init__(self, path: Path):
        refuse_symlinks(path)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute("PRAGMA journal_mode=WAL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > 6:
            self.db.close()
            raise ValueError("Database schema is newer than this PhotoCull version")
        if version == 0:
            self.db.executescript(MIGRATION_1)
            version = 1
        if version == 1:
            from photocull.duplicate_storage import MIGRATION_2

            self.db.executescript(MIGRATION_2)
            version = 2
        if version == 2:
            from photocull.embeddings import MIGRATION_3

            self.db.executescript(MIGRATION_3)
            version = 3
        if version == 3:
            from photocull.event_storage import MIGRATION_4

            self.db.executescript(MIGRATION_4)
            version = 4
        if version == 4:
            from photocull.ranking_service import MIGRATION_5

            self.db.executescript(MIGRATION_5)
            version = 5
        if version == 5:
            from photocull.preference_storage import MIGRATION_6

            self.db.executescript(MIGRATION_6)
        # Additive compatibility with an unreleased Phase 6 development database.
        columns = {r[1] for r in self.db.execute("PRAGMA table_info(preference_partitions)")}
        if "group_id" not in columns:
            with self.db:
                self.db.execute(
                    "ALTER TABLE preference_partitions ADD COLUMN group_id TEXT NOT NULL DEFAULT ''"
                )
        path.chmod(0o600)

    def close(self):
        self.db.close()

    def version(self, component, algorithm_version, parameters) -> str:
        ph = parameter_hash(parameters)
        identifier = parameter_hash(
            {"component": component, "version": algorithm_version, "parameters": ph}
        )
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO analysis_versions VALUES (?,?,?,?,?)",
                (identifier, component, algorithm_version, ph, json.dumps(parameters)),
            )
        return identifier

    def create_run(self, root: Path, mode: str, config: dict) -> str:
        identifier = uuid.uuid4().hex
        with self.db:
            self.db.execute(
                """INSERT INTO scan_runs
                (id,source_root,mode,status,started_at,app_version,config_json)
                VALUES (?,?,?,'queued',?,?,?)""",
                (
                    identifier,
                    str(root.resolve()),
                    mode,
                    now(),
                    __version__,
                    json.dumps(config, sort_keys=True),
                ),
            )
        return identifier

    def update_run(self, run_id, status, progress, finished=False):
        with self.db:
            self.db.execute(
                """UPDATE scan_runs SET status=?, progress_json=?, finished_at=?
                WHERE id=?""",
                (status, json.dumps(progress), now() if finished else None, run_id),
            )

    def get_run(self, run_id):
        row = self.db.execute("SELECT * FROM scan_runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown scan run")
        return dict(row)

    def runs(self):
        return [
            dict(r)
            for r in self.db.execute("SELECT * FROM scan_runs ORDER BY started_at DESC LIMIT 30")
        ]

    def cancel(self, run_id):
        with self.db:
            self.db.execute("UPDATE scan_runs SET cancel_requested=1 WHERE id=?", (run_id,))

    def cancelled(self, run_id):
        return bool(self.get_run(run_id)["cancel_requested"])

    def source(self, path: Path):
        row = self.db.execute(
            "SELECT * FROM source_photos WHERE path=?", (str(path.resolve()),)
        ).fetchone()
        return dict(row) if row else None

    def save_source(self, metadata: dict) -> int:
        with self.db:
            self.db.execute(
                """INSERT INTO source_photos
                (path,fingerprint,content_sha256,metadata_json,updated_at) VALUES (?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET fingerprint=excluded.fingerprint,
                content_sha256=excluded.content_sha256,metadata_json=excluded.metadata_json,
                updated_at=excluded.updated_at""",
                (
                    metadata["path"],
                    metadata["fingerprint"],
                    metadata["content_sha256"],
                    json.dumps(metadata),
                    now(),
                ),
            )
        return self.source(Path(metadata["path"]))["id"]

    def attach(self, run_id, photo_id, fingerprint):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO run_photos VALUES (?,?,?)", (run_id, photo_id, fingerprint)
            )

    def cached(self, table, photo_id, fingerprint, analysis_id):
        if table not in {"quality_measurements", "perceptual_hashes", "thumbnail_metadata"}:
            raise ValueError("Unknown analysis table")
        row = self.db.execute(
            f"SELECT * FROM {table} WHERE photo_id=? AND fingerprint=? AND analysis_id=?",
            (photo_id, fingerprint, analysis_id),
        ).fetchone()
        return dict(row) if row else None

    def save_quality(self, photo_id, fingerprint, analysis_id, result):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO quality_measurements VALUES (?,?,?,?,?,?,?,?)",
                (
                    photo_id,
                    fingerprint,
                    analysis_id,
                    now(),
                    json.dumps(result["raw"]),
                    json.dumps(result["normalized"]),
                    json.dumps(result["warnings"]),
                    result["technical_quality_v1"],
                ),
            )

    def save_hashes(self, photo_id, fingerprint, analysis_id, result):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO perceptual_hashes VALUES (?,?,?,?,?,?,?)",
                (
                    photo_id,
                    fingerprint,
                    analysis_id,
                    now(),
                    result["phash"],
                    result["dhash"],
                    result["ahash"],
                ),
            )

    def save_thumbnail(self, photo_id, fingerprint, analysis_id, result):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO thumbnail_metadata VALUES (?,?,?,?,?,?,?,?)",
                (
                    photo_id,
                    fingerprint,
                    analysis_id,
                    now(),
                    result["path"],
                    result["width"],
                    result["height"],
                    result["cache_key"],
                ),
            )

    def failure(self, run_id, path, stage, exc):
        with self.db:
            self.db.execute(
                """INSERT INTO processing_failures
                (run_id,path,stage,error_type,message,generated_at) VALUES (?,?,?,?,?,?)""",
                (
                    run_id,
                    str(path) if path else None,
                    stage,
                    type(exc).__name__,
                    str(exc)[:2000],
                    now(),
                ),
            )

    def failures(self, run_id):
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM processing_failures WHERE run_id=? ORDER BY id", (run_id,)
            )
        ]

    def results(self, run_id):
        # Use the IDs actually used by this run, even after runtime/library upgrades.
        run = self.get_run(run_id)
        ids = json.loads(run["progress_json"]).get("analysis_ids", {})
        output = []
        for row in self.db.execute(
            """SELECT s.*,r.fingerprint AS run_fingerprint
            FROM source_photos s JOIN run_photos r ON s.id=r.photo_id WHERE r.run_id=?
            ORDER BY s.path""",
            (run_id,),
        ):
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json"))
            from photocull.scanner import fingerprint

            try:
                live = fingerprint(refuse_symlinks(Path(item["path"])))
            except (OSError, ValueError):
                live = None
            item["source_changed_since_run"] = live != item["run_fingerprint"]
            for table, key, component in (
                ("quality_measurements", "quality", "QualityAnalyzer"),
                ("perceptual_hashes", "hashes", "PerceptualHashService"),
                ("thumbnail_metadata", "thumbnail", "ThumbnailService"),
            ):
                item[key] = self.cached(
                    table, item["id"], item["run_fingerprint"], ids.get(component, "")
                )
            output.append(item)
        return output

    def clear_derived(self):
        with self.db:
            self.db.execute("DELETE FROM ranking_results")
            self.db.execute("DELETE FROM event_scan_links")
            self.db.execute("DELETE FROM event_runs")
            self.db.execute("DELETE FROM embedding_records")
            self.db.execute("DELETE FROM duplicate_scan_links")
            self.db.execute("DELETE FROM duplicate_runs")
            for table in ("quality_measurements", "perceptual_hashes", "thumbnail_metadata"):
                self.db.execute(f"DELETE FROM {table}")
            # Reclaim sensitive derived values from the main database/free pages and WAL.
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.execute("VACUUM")

    def counts(self):
        return {
            table: self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "source_photos",
                "scan_runs",
                "quality_measurements",
                "perceptual_hashes",
                "thumbnail_metadata",
                "user_decisions",
            )
        }
