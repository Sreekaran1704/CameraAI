"""Local event timeline and persistent manual corrections."""

from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

from photocull.cache import refuse_symlinks
from photocull.duplicates import features_from_rows
from photocull.event_storage import EventStore
from photocull.events import discover_for_scan
from photocull.storage import Repository


def thumbnail(row, cache, caption):
    thumb = row.get("thumbnail")
    if not thumb:
        st.caption(caption)
        return
    try:
        path = refuse_symlinks(Path(thumb["path"]))
        if path.parent == cache.root / "thumbnails" and path.is_file():
            st.image(str(path), caption=caption, width="stretch")
    except (OSError, ValueError):
        st.caption("Thumbnail unavailable")


def render_events(settings, cache, run_id):
    st.subheader("Events")
    st.caption("Likely occasions from capture time. Neutral names until you rename them.")
    repo = Repository(cache.root / "metadata.db")
    try:
        rows = repo.results(run_id)
        photos = features_from_rows(rows, cache, verify=False)
        store = EventStore(repo)
        result = store.for_scan(run_id, photos)
        if st.button("Discover / refresh events") or result is None:
            if repo.get_run(run_id)["status"] in {"queued", "running"}:
                st.info("Event discovery will run when analysis finishes.")
                return
            with st.spinner("Discovering events locally"):
                with cache.lock():
                    result = discover_for_scan(repo, run_id, settings)
        if result is None:
            return
        by_id = {str(r["id"]): r for r in rows}
        for col, label, value in zip(
            st.columns(3),
            ("Events", "Unassigned photos", "Low confidence"),
            (result["event_count"], result["unassigned_count"], result["low_confidence_count"]),
            strict=True,
        ):
            col.metric(label, value)
        st.caption(
            f"Method: {result['parameters']['method']} · "
            f"Gap: {result['parameters']['gap_minutes']:g} minutes · "
            "Timezone-aware EXIF, naive EXIF, and filesystem times form separate timelines."
        )
        if result.get("manual_correction_conflicts"):
            st.warning("Some originals changed; saved corrections need review.")
        for warning in result.get("warnings", []):
            st.warning(warning)
        events = result["events"]
        if events:
            st.write("Event timeline")
            import altair as alt

            timeline = []
            for event in events:
                tiers = {result["assignments"][i]["timestamp_tier"] for i in event["members"]}
                if tiers == {"exif_timezone"} and event["start"] and event["end"]:
                    timeline.append(
                        {
                            "Event": event["name"],
                            "Start": datetime.fromisoformat(event["start"])
                            .astimezone(UTC)
                            .isoformat(),
                            "End": datetime.fromisoformat(event["end"]).astimezone(UTC).isoformat(),
                            "Photos": len(event["members"]),
                        }
                    )
            if timeline:
                pages = max(1, (len(timeline) + 19) // 20)
                if st.session_state.get("timeline_page", 1) > pages:
                    st.session_state["timeline_page"] = 1
                window = timeline[
                    (int(st.session_state.get("timeline_page", 1)) - 1) * 20 : int(
                        st.session_state.get("timeline_page", 1)
                    )
                    * 20
                ]
                st.number_input(
                    "Timeline page", 1, max(1, (len(timeline) + 19) // 20), key="timeline_page"
                )
                data = alt.Data(values=window)
                encoding = {
                    "x": alt.X(
                        "Start:T",
                        title="Timezone-aware capture time (UTC)",
                        scale=alt.Scale(type="utc"),
                    ),
                    "y": alt.Y("Event:N", sort=None),
                    "tooltip": ["Event:N", "Start:N", "End:N", "Photos:Q"],
                }
                bars = alt.Chart(data).mark_bar(color="#568e83").encode(**encoding, x2="End:T")
                points = alt.Chart(data).mark_point(color="#27685b", filled=True).encode(**encoding)
                st.altair_chart(bars + points, width="stretch")
            st.caption("Naive and filesystem timestamps stay in separate provenance rows below.")

            st.dataframe(
                [
                    {
                        "Event": e["name"],
                        "Start": e["start"],
                        "End": e["end"],
                        "Photos": len(e["members"]),
                        "Manually edited": e["manual"],
                        "Timestamp tier": ", ".join(
                            sorted(
                                {result["assignments"][i]["timestamp_tier"] for i in e["members"]}
                            )
                        ),
                    }
                    for e in events
                ],
                hide_index=True,
                width="stretch",
            )
            total_pages = max(1, (len(events) + 5) // 6)
            page = st.number_input("Event card page", 1, total_pages, 1)
            for event in events[(page - 1) * 6 : page * 6]:
                with st.container(border=True):
                    st.write(f"**{event['name']}** · {len(event['members'])} photos")
                    st.caption(
                        f"{event['start'] or 'Unknown time'} → {event['end'] or 'Unknown time'}"
                    )
                    for col, identifier in zip(
                        st.columns(3), event["representatives"], strict=False
                    ):
                        with col:
                            thumbnail(
                                by_id[identifier], cache, by_id[identifier]["metadata"]["filename"]
                            )
            labels = {e["id"]: f"{e['name']} · {len(e['members'])} photos" for e in events}
            selected_id = st.selectbox("Open event", list(labels), format_func=labels.get)
            selected = next(e for e in events if e["id"] == selected_id)
            from photocull.ui.best_photos import event_highlights

            event_highlights(settings, cache, repo, run_id, selected["members"], selected["id"])
            st.write(f"Members of **{selected['name']}**")
            st.caption(selected["representative_reason"])
            member_pages = max(1, (len(selected["members"]) + 11) // 12)
            member_page = st.number_input("Member page", 1, member_pages, 1, key=selected_id)
            for start in range(
                (member_page - 1) * 12, min(member_page * 12, len(selected["members"])), 3
            ):
                for col, identifier in zip(
                    st.columns(3), selected["members"][start : start + 3], strict=False
                ):
                    with col:
                        a = result["assignments"][identifier]
                        thumbnail(
                            by_id[identifier], cache, by_id[identifier]["metadata"]["filename"]
                        )
                        st.caption(f"{a['status']} · {a['reason']}")
            with st.expander("Rename event"):
                with st.form("rename-event"):
                    name = st.text_input("Event name", selected["name"], max_chars=120)
                    if st.form_submit_button("Save name"):
                        store.correct(result, "rename", event_id=selected_id, name=name)
                        st.rerun()
            with st.expander("Move, remove, or split photos"):
                with st.form("edit-members"):
                    identifiers = st.multiselect(
                        "Selected photos",
                        selected["members"],
                        format_func=lambda i: by_id[i]["metadata"]["filename"],
                    )
                    action = st.selectbox("Action", ["remove", "move", "split"])
                    target = st.selectbox("Destination event", list(labels), format_func=labels.get)
                    split_name = st.text_input("Split event name", "New event", max_chars=120)
                    if st.form_submit_button("Apply photo correction"):
                        store.correct(
                            result,
                            action,
                            event_id=selected_id,
                            target_id=target,
                            photo_ids=identifiers,
                            name=split_name if action == "split" else None,
                        )
                        st.rerun()
            if len(events) > 1:
                with st.expander("Merge events"):
                    with st.form("merge-events"):
                        options = [i for i in labels if i != selected_id]
                        target = st.selectbox("Merge into", options, format_func=labels.get)
                        if st.form_submit_button("Merge selected event"):
                            store.correct(result, "merge", event_id=selected_id, target_id=target)
                            st.rerun()
        review = [a for a in result["assignments"].values() if a["status"] != "EVENT_MEMBER"]
        if review:
            with st.expander("Review unassigned and low-confidence photos", expanded=not events):
                st.dataframe(
                    [
                        {
                            "Photo": by_id[a["photo_id"]]["metadata"]["filename"],
                            "Status": a["status"],
                            "Timestamp": a["timestamp_tier"],
                            "Confidence": a["timestamp_confidence"],
                            "Reason": a["reason"],
                        }
                        for a in review
                    ],
                    hide_index=True,
                    width="stretch",
                )
                identifier = st.selectbox(
                    "Review photo",
                    [a["photo_id"] for a in review],
                    format_func=lambda i: by_id[i]["metadata"]["filename"],
                )
                thumbnail(by_id[identifier], cache, by_id[identifier]["metadata"]["filename"])
                if events:
                    labels = {e["id"]: e["name"] for e in events}
                    target = st.selectbox("Assign to event", list(labels), format_func=labels.get)
                    if st.button("Save reviewed assignment"):
                        store.correct(result, "move", target_id=target, photo_ids=[identifier])
                        st.rerun()
        with st.expander("Event provenance"):
            st.json({k: v for k, v in result.items() if k not in {"events", "assignments"}})
    except (ValueError, OSError) as exc:
        st.error(str(exc))
    finally:
        repo.close()
