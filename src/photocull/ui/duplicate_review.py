"""Local duplicate review, technical representatives and persisted human corrections."""

import json
import math
from pathlib import Path

import streamlit as st

from photocull.cache import refuse_symlinks
from photocull.duplicate_storage import DuplicateStore
from photocull.duplicates import detect_for_scan, features_from_rows
from photocull.similarity import Relationship
from photocull.storage import Repository


def render_duplicate_review(config, cache, scan_id):
    st.subheader("Duplicate Review")
    st.caption(
        "Review before choosing. Burst frames may have different expressions or poses. "
        "PhotoCull never deletes or moves originals."
    )
    repo = Repository(cache.root / "metadata.db")
    try:
        store = DuplicateStore(repo)
        rows = repo.results(scan_id)
        features = features_from_rows(rows, cache, verify=False)
        current = {p.id: p for p in features}
        by_id = {str(r["id"]): r for r in rows}
        result = store.for_scan(scan_id)
        if not result:
            st.info(
                "Analyze this folder to calculate duplicates and bursts. Phase 1 history "
                "can be upgraded with Recalculate groups."
            )
        if st.button("Recalculate groups", type="primary"):
            try:
                with cache.lock():
                    result = detect_for_scan(repo, scan_id, config)
            except (ValueError, OSError) as exc:
                st.error(str(exc))
        if result is None:
            return
        progress = json.loads(repo.get_run(scan_id)["progress_json"])
        embedding_stats = result.get(
            "embeddings", progress.get("duplicates", {}).get("embeddings", {})
        )
        if embedding_stats.get("warning"):
            st.warning(embedding_stats["warning"])
        if embedding_stats.get("enabled"):
            st.caption(
                f"Local embedding model: {embedding_stats['model']} · "
                f"Device: {embedding_stats['device']} · "
                f"Embedding cache hits: {embedding_stats['cache_hits']}"
            )
            with st.expander("Embedding inference measurements"):
                st.json(embedding_stats)
        if any(r["source_changed_since_run"] for r in rows):
            st.warning(
                "Sources changed or became unavailable. Start a new folder analysis. "
                "Stale group recommendations and savings are hidden."
            )
            return
        blocked, suppressed = store.corrections(features)
        # Do not show stale recommendations after a saved correction until recomputed.
        groups = [
            g
            for g in result["groups"]
            if g["signature"] not in suppressed and all(i in current for i in g["members"])
        ]
        violates = False
        if blocked:
            for group in groups:
                identifiers = set(group["members"])
                if any(a in identifiers and b in identifiers for a, b in blocked):
                    violates = True
                    break
        if len(groups) != len(result["groups"]) or violates:
            st.warning(
                "Saved corrections changed these results. Recalculate groups to refresh "
                "recommendations and storage estimates."
            )
            return
        exact = [g for g in groups if g["type"] == Relationship.EXACT_DUPLICATE]
        near = [g for g in groups if g["type"] == Relationship.NEAR_DUPLICATE]
        bursts = [g for g in groups if g["type"] == Relationship.BURST_GROUP]
        for column, label, value in zip(
            st.columns(4),
            ["Exact groups", "Files in exact groups", "Near groups", "Burst groups"],
            [len(exact), sum(len(g["members"]) for g in exact), len(near), len(bursts)],
            strict=True,
        ):
            column.metric(label, value)
        left, right = st.columns(2)
        left.metric(
            "Exact reclaimable file bytes", f"{result['exact_reclaimable_bytes'] / 1e6:.2f} MB"
        )
        right.metric(
            "Potential near-duplicate savings", f"{result['near_candidate_bytes'] / 1e6:.2f} MB"
        )
        st.caption(
            "Exact estimate retains one copy per group and excludes known hardlinks. "
            "Near estimate: potential savings if you choose to remove redundant alternatives. "
            "It excludes exact-copy alternatives; filesystem compression may change actual space."
        )
        if result["statistics"]["budget_limited"]:
            st.warning("Candidate search reached a work limit. Some matches may be missed.")
        st.caption(
            "Reliability scores are heuristic, not calibrated probabilities. "
            "Pixel/hash matches do not establish artistic preference."
        )
        if not groups:
            st.info("No sufficiently supported groups in this analysis.")
            return
        kinds = ["All", "EXACT_DUPLICATE", "NEAR_DUPLICATE", "BURST_GROUP"]
        kind = st.selectbox("Relationship type", kinds)
        visible = [g for g in groups if kind == "All" or g["type"] == kind]
        if not visible:
            st.info("No groups of this type.")
            return
        index = st.selectbox(
            "Group",
            range(len(visible)),
            format_func=lambda i: (
                f"Group {i + 1} · "
                f"{visible[i]['type'].replace('_', ' ').title()} · "
                f"{len(visible[i]['members'])} files"
            ),
        )
        group = visible[index]
        rep_row = by_id[group["representative"]]
        st.write(f"★ Recommended representative: **{rep_row['metadata']['filename']}**")
        st.caption(group["representative_reason"])
        if group["type"] == Relationship.BURST_GROUP:
            st.info("A burst describes a moment, not redundancy. Inspect each frame.")
        members = [current[i] for i in group["members"]]
        if st.button("Mark group as Not Duplicate", key=f"deny-group-{group['id']}"):
            try:
                with cache.lock():
                    store.not_duplicate(members)
                    detect_for_scan(repo, scan_id, config)
                st.rerun()
            except (ValueError, OSError) as exc:
                st.error(str(exc))
        page = int(
            st.number_input(
                "Thumbnail page",
                min_value=1,
                max_value=max(1, math.ceil(len(members) / 12)),
                value=1,
                key=f"member-page-{group['id']}",
            )
        )
        selected_members = group["members"][(page - 1) * 12 : page * 12]
        decisions = {
            str(r["photo_id"]): r["decision"]
            for r in repo.db.execute("SELECT * FROM user_decisions")
        }
        columns = st.columns(3)
        for i, identifier in enumerate(selected_members):
            row = by_id[identifier]
            with columns[i % 3]:
                st.write(row["metadata"]["filename"])
                if identifier == group["representative"]:
                    st.caption("★ Recommended representative")
                thumb = row["thumbnail"]
                if thumb:
                    try:
                        path = refuse_symlinks(Path(thumb["path"]))
                        if path.parent == cache.root / "thumbnails" and path.is_file():
                            st.image(str(path), width="stretch")
                    except ValueError:
                        st.warning("Unsafe thumbnail refused.")
                feature = current[identifier]
                normalized = feature.quality["normalized"]
                st.caption(
                    f"Sharpness {normalized['sharpness']:.2f} · "
                    f"Exposure {normalized['exposure']:.2f} · "
                    f"{feature.width * feature.height / 1e6:.2f} MP"
                )
                st.caption(f"Decision: {decisions.get(identifier, 'unmarked')}")
                for label, decision in (
                    ("Keep", "keep"),
                    ("Favorite", "favorite"),
                    ("Review Later", "review"),
                ):
                    if st.button(label, key=f"{group['id']}-{identifier}-{decision}"):
                        store.decide(identifier, decision)
                        st.rerun()
                if st.button("Mark as Not Duplicate", key=f"deny-{group['id']}-{identifier}"):
                    try:
                        with cache.lock():
                            store.not_duplicate(members, identifier)
                            detect_for_scan(repo, scan_id, config)
                        st.rerun()
                    except (ValueError, OSError) as exc:
                        st.error(str(exc))
        with st.expander("Grouping evidence and provenance"):
            st.json(
                {
                    "reason": group["reason"],
                    "maximum_pHash_distance": group["max_phash_distance"],
                    "evidence": group["evidence"],
                    "analysis_id": result["analysis_id"],
                    "generated_at": result["generated_at"],
                }
            )
    finally:
        repo.close()
