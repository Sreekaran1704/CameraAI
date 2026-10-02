"""Immutable automatic snapshots plus persistent fingerprint-scoped manual overrides."""

import copy
import json
import uuid

from photocull.events import assignment, event_record

MIGRATION_4 = """
BEGIN IMMEDIATE;
CREATE TABLE event_runs (
    dataset_key TEXT PRIMARY KEY, result_json TEXT NOT NULL
);
CREATE TABLE event_scan_links (
    scan_id TEXT PRIMARY KEY REFERENCES scan_runs(id),
    dataset_key TEXT NOT NULL REFERENCES event_runs(dataset_key)
);
CREATE TABLE manual_events (
    id TEXT PRIMARY KEY, name TEXT NOT NULL
);
CREATE TABLE event_overrides (
    photo_id INTEGER PRIMARY KEY REFERENCES source_photos(id),
    fingerprint TEXT NOT NULL,
    event_id TEXT REFERENCES manual_events(id)
);
PRAGMA user_version=4;
COMMIT;
"""


class EventStore:
    def __init__(self, repository):
        self.repo = repository
        self.db = repository.db

    def cached(self, key):
        row = self.db.execute(
            "SELECT result_json FROM event_runs WHERE dataset_key=?", (key,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, key, result):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO event_runs VALUES (?,?)",
                (key, json.dumps(result, allow_nan=False)),
            )

    def link(self, scan_id, key):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO event_scan_links VALUES (?,?)", (scan_id, key))

    def for_scan(self, scan_id, photos, vectors=None):
        row = self.db.execute(
            "SELECT dataset_key FROM event_scan_links WHERE scan_id=?", (scan_id,)
        ).fetchone()
        return self.overlay(self.cached(row[0]), photos, vectors) if row else None

    def overlay(self, automatic, photos, vectors=None):
        result = copy.deepcopy(automatic)
        by_id = {p.id: p for p in photos}
        result["assignments"] = {i: a for i, a in result["assignments"].items() if i in by_id}
        result["excluded_unavailable_since_event_run"] = len(automatic["assignments"]) - len(
            result["assignments"]
        )
        overrides = {}
        conflicts = []
        for row in self.db.execute("SELECT * FROM event_overrides"):
            identifier = str(row["photo_id"])
            if identifier not in by_id:
                continue
            if row["fingerprint"] != by_id[identifier].fingerprint:
                conflicts.append(identifier)
                continue
            overrides[identifier] = row["event_id"]
        events = []
        for event in result["events"]:
            members = [by_id[i] for i in event["members"] if i in by_id and i not in overrides]
            if members:
                if len(members) == len(event["members"]):
                    events.append(event)
                else:
                    events.append(event_record(members, vectors, event["id"], event["name"]))
        names = {r["id"]: r["name"] for r in self.db.execute("SELECT * FROM manual_events")}
        for event_id in sorted({e for e in overrides.values() if e is not None}):
            members = [by_id[i] for i, e in overrides.items() if e == event_id]
            events.append(event_record(members, vectors, event_id, names[event_id], True))
        for identifier, event_id in overrides.items():
            result["assignments"][identifier] = assignment(
                by_id[identifier],
                event_id,
                "EVENT_MEMBER" if event_id else "UNASSIGNED",
                "Manual assignment" if event_id else "Manually removed from event",
            )
            result["assignments"][identifier]["manual"] = True
        for identifier in conflicts:
            if identifier in result["assignments"]:
                result["assignments"][identifier]["status"] = "LOW_CONFIDENCE"
                result["assignments"][identifier]["reason"] = (
                    "Source fingerprint changed; saved manual correction needs review"
                )
        result["events"] = sorted(events, key=lambda e: (e["start"] or "", e["id"]))
        result["event_count"] = len(events)
        result["unassigned_count"] = sum(
            a["status"] == "UNASSIGNED" for a in result["assignments"].values()
        )
        result["low_confidence_count"] = sum(
            a["status"] == "LOW_CONFIDENCE" for a in result["assignments"].values()
        )
        result["manual_correction_conflicts"] = conflicts
        return result

    def correct(self, result, action, event_id=None, target_id=None, photo_ids=(), name=None):
        """Atomically materialize affected events and apply a reviewable local edit."""
        events = {e["id"]: e for e in result["events"]}
        assignments = result["assignments"]
        selected = list(dict.fromkeys(str(i) for i in photo_ids))
        if action not in {"rename", "merge", "split", "move", "remove"}:
            raise ValueError("Unknown event correction")
        if name is not None and (not name.strip() or len(name.strip()) > 120):
            raise ValueError("Event names must contain 1–120 characters")
        if action in {"rename", "merge", "split"} and event_id not in events:
            raise ValueError("Unknown source event")
        if action in {"merge", "move"} and target_id not in events:
            raise ValueError("Unknown destination event")
        if action == "merge" and event_id == target_id:
            raise ValueError("Choose two different events")
        if action == "rename" and name is None:
            raise ValueError("A name is required")
        if action in {"split", "move", "remove"} and (
            not selected or any(i not in assignments for i in selected)
        ):
            raise ValueError("Choose valid photos")
        if action == "split" and (not set(selected) < set(events[event_id]["members"])):
            raise ValueError("Split must select a nonempty proper subset of the event")
        # Validate every affected member against live originals before any transaction.
        from pathlib import Path

        from photocull.cache import refuse_symlinks
        from photocull.scanner import fingerprint

        affected = set(selected)
        for identifier in (event_id, target_id):
            if identifier in events:
                affected.update(events[identifier]["members"])
        for identifier in affected:
            source = self.db.execute(
                "SELECT path, fingerprint FROM source_photos WHERE id=?", (int(identifier),)
            ).fetchone()
            if (
                not source
                or source["fingerprint"] != assignments[identifier]["fingerprint"]
                or fingerprint(refuse_symlinks(Path(source["path"])))
                != assignments[identifier]["fingerprint"]
            ):
                raise ValueError("Sources changed; refresh the analysis before editing")
        mapping = {}

        def materialize(identifier):
            if identifier in mapping:
                return mapping[identifier]
            event = events[identifier]
            manual_id = identifier if event.get("manual") else "manual-" + uuid.uuid4().hex
            self.db.execute(
                "INSERT OR IGNORE INTO manual_events VALUES (?,?)", (manual_id, event["name"])
            )
            for photo_id in event["members"]:
                self.db.execute(
                    "INSERT OR REPLACE INTO event_overrides VALUES (?,?,?)",
                    (int(photo_id), assignments[photo_id]["fingerprint"], manual_id),
                )
            mapping[identifier] = manual_id
            return manual_id

        with self.db:
            if action == "rename":
                identifier = materialize(event_id)
                self.db.execute(
                    "UPDATE manual_events SET name=? WHERE id=?", (name.strip(), identifier)
                )
            elif action == "merge":
                source, target = materialize(event_id), materialize(target_id)
                self.db.execute(
                    "UPDATE event_overrides SET event_id=? WHERE event_id=?", (target, source)
                )
            else:
                if action == "split":
                    materialize(event_id)
                    target = "manual-" + uuid.uuid4().hex
                    self.db.execute(
                        "INSERT INTO manual_events VALUES (?,?)",
                        (target, name.strip() if name else "New event"),
                    )
                elif action == "move":
                    target = materialize(target_id)
                else:
                    target = None
                for identifier in selected:
                    old = assignments[identifier]["event_id"]
                    if old in events:
                        materialize(old)
                    self.db.execute(
                        "INSERT OR REPLACE INTO event_overrides VALUES (?,?,?)",
                        (int(identifier), assignments[identifier]["fingerprint"], target),
                    )
        return mapping
