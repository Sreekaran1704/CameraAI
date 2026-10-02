"""Public-safe upload-only edition. Never imports the filesystem UI entry point."""

import streamlit as st

from photocull.config import Config, RankingConfig
from photocull.preference_storage import PreferenceStore, consistency
from photocull.preferences import candidates, feature_records, personalized
from photocull.ranking import export_manifest, rank, shortlist
from photocull.sources import UploadedImageSource
from photocull.ui.style import apply_style, bundled_sources
from photocull.web_session import (
    MAX_IMAGES,
    MAX_PREFERENCE_ACTIONS,
    MAX_TOTAL_BYTES,
    REGISTRY,
    DemoBusyError,
    DemoLimitError,
    add_sources,
    start_cleanup,
)

PRIVACY = (
    "Uploaded images are processed temporarily for this session and are not "
    "intentionally persisted by PhotoCull."
)


def display_card(session, item, event_names, key):
    identifier = item["photo_id"]
    with st.container(border=True):
        st.image(session.thumbnails[identifier], width="stretch")
        st.write(
            f"**#{item.get('rank', item.get('raw_rank', 1))} · "
            f"{session.rows[identifier]['metadata']['filename']}**"
        )
        st.caption(event_names.get(identifier, "No reliable event time"))
        st.caption(f"Technical quality {item['quality']:.3f}")
        with st.expander("Why this photo"):
            for reason in item["explanation"]:
                st.write(reason)
            for reason in item["weaker_points"]:
                st.caption(reason)
            st.caption("Technical signals do not establish aesthetic or emotional superiority.")
        decision = st.selectbox(
            "Your choice",
            ["unmarked", "keep", "favorite", "review"],
            index=["unmarked", "keep", "favorite", "review"].index(
                session.decisions.get(identifier, "unmarked")
            ),
            key=f"{key}-{identifier}",
        )
        session.decisions[identifier] = decision


def result_views(session):
    names = {i: e["name"] for e in session.events["events"] for i in e["members"]}
    view = st.segmented_control(
        "Explore your photos",
        ["Overview", "Review", "Events", "Best Photos", "Preferences", "Export"],
        default="Overview",
        key=f"view-{session.token}",
    )
    if view == "Overview":
        counts = {
            kind: sum(g["type"] == kind for g in session.duplicates["groups"])
            for kind in ("EXACT_DUPLICATE", "NEAR_DUPLICATE", "BURST_GROUP")
        }
        for col, label, value in zip(
            st.columns(3),
            ("Photos analyzed", "Duplicate groups", "Event groups"),
            (
                len(session.photos),
                counts["EXACT_DUPLICATE"] + counts["NEAR_DUPLICATE"],
                session.events["event_count"],
            ),
            strict=True,
        ):
            col.metric(label, value)
        for col, label, value in zip(
            st.columns(3),
            ("Exact groups", "Near groups", "Burst groups"),
            counts.values(),
            strict=True,
        ):
            col.metric(label, value)
        warnings = sum(bool(p.quality.get("warnings")) for p in session.photos)
        st.caption(
            f"{warnings} photos with technical warnings · "
            f"{session.events['unassigned_count']} without reliable event time"
        )
        st.caption(
            "Potential exact-copy bytes: "
            f"{session.duplicates['exact_reclaimable_bytes'] / 1024:.1f} KiB. "
            "This is an estimate; PhotoCull never deletes images."
        )
        st.write("**A first look**")
        for col, item in zip(st.columns(3), session.ranking["selected"][:3], strict=False):
            with col:
                display_card(session, item, names, "overview")
    elif view == "Review":
        groups = session.duplicates["groups"]
        if not groups:
            st.info("No conservative duplicate or burst groups found.")
            return
        index = st.selectbox(
            "Review group",
            range(len(groups)),
            format_func=lambda i: (
                f"{groups[i]['type'].replace('_', ' ').title()} "
                f"· {len(groups[i]['members'])} photos"
            ),
        )
        group = groups[index]
        st.caption(group["representative_reason"])
        st.caption("Burst groups mark a moment and do not imply a deletion recommendation.")
        by_id = {r["photo_id"]: r for r in session.ranking["ranked"]}
        for identifier in group["members"]:
            display_card(session, by_id[identifier], names, "review")
        with st.expander("Evidence"):
            st.json(
                {
                    "reason": group["reason"],
                    "maximum_hash_distance": group["max_phash_distance"],
                    "evidence": group["evidence"],
                }
            )
    elif view == "Events":
        events = session.events["events"]
        if not events:
            st.info(
                "No usable EXIF capture times. Upload times are never invented as camera events."
            )
        for event in events:
            with st.container(border=True):
                st.write(f"**{event['name']}** · {len(event['members'])} photos")
                st.caption(f"{event['start']} → {event['end']}")
                st.caption(event["representative_reason"])
                for col, identifier in zip(st.columns(3), event["representatives"], strict=False):
                    with col:
                        st.image(session.thumbnails[identifier], width="stretch")
        st.caption("Time-only events · timezone-aware and naive EXIF remain separate.")
    elif view == "Best Photos":
        mode = st.radio("Ranking mode", ["Generic", "Personalized"], horizontal=True)
        variant = st.selectbox(
            "Generic ranking",
            ["B", "A"],
            disabled=mode == "Personalized",
            format_func=lambda v: (
                "B · Quality and diversity" if v == "B" else "A · Technical quality"
            ),
        )
        k = st.selectbox("Shortlist size", [10, 20])
        data = session.data()
        if mode == "Personalized":
            records = feature_records(data)
            model = PreferenceStore(state=session.preference_state).model(records)
            result = personalized(data, Config(), model, records, k=k)
            if not result["personalization_active"]:
                st.info("Personalization is not active yet. Using generic Ranking B.")
        else:
            cfg = RankingConfig(variant=variant)
            ranked = rank(session.photos, cfg)
            selected = shortlist(
                session.photos,
                ranked["ranked"],
                k,
                cfg,
                groups=session.duplicates["groups"],
                coverage={p.id: names.get(p.id, "unassigned") for p in session.photos},
            )
            result = {**ranked, **selected}
        session.ranking = result
        st.caption(
            f"{len(result['selected'])} recommendations · "
            "one per known duplicate/burst group · no forced fillers"
        )
        for start in range(0, len(result["selected"]), 3):
            for col, item in zip(
                st.columns(3), result["selected"][start : start + 3], strict=False
            ):
                with col:
                    display_card(session, item, names, "best")
    elif view == "Preferences":
        st.write("**Teach PhotoCull My Taste · session only**")
        records = feature_records(session.data())
        store = PreferenceStore(state=session.preference_state)
        store.allocate(records)
        examples = store.examples(records)
        model = store.model(records)
        st.caption(f"{model['training_comparisons']} / 50 decisive training comparisons")
        st.info(
            "Personalization is not active yet."
            if not model["active"]
            else "Personalized ranking is active (experimental)."
        )
        st.caption(
            "Activation also needs independent held-out improvement. This small demo "
            "may not contain enough groups; use Local Edition for a private study."
        )
        comparison = st.radio("Preference set", ["Training", "Held-out"], horizontal=True)
        partition = "train" if comparison == "Training" else "holdout"
        pool = candidates(
            session.data(), records, [e["pair_key"] for e in examples], partition_filter=partition
        )
        if pool:
            pair = pool[0]
            for side, col in zip(("a", "b"), st.columns(2), strict=True):
                with col:
                    st.image(session.thumbnails[pair[side]], caption=f"Photo {side.upper()}")
            for label, choice, col in zip(
                ("Prefer A", "Prefer B", "Tie", "Skip"),
                ("a", "b", "tie", "skip"),
                st.columns(4),
                strict=True,
            ):
                with col:
                    if st.button(
                        label,
                        key=f"pref-{choice}",
                        width="stretch",
                        disabled=session.preference_actions >= MAX_PREFERENCE_ACTIONS,
                    ):
                        store.save(records[pair["a"]], records[pair["b"]], choice)
                        session.preference_actions += 1
                        st.rerun()
        else:
            st.caption("No fresh comparisons in this set.")
        if session.preference_actions >= MAX_PREFERENCE_ACTIONS:
            st.info("Session preference budget reached. Reset preferences to start again.")
        if st.button(
            "Undo latest preference",
            disabled=not store.feedback() or session.preference_actions >= MAX_PREFERENCE_ACTIONS,
        ):
            store.undo()
            session.preference_actions += 1
            st.rerun()
        st.json(consistency(examples))
        if st.button("Reset session preferences"):
            store.reset()
            session.preference_actions = 0
            st.rerun()
    elif view == "Export":
        st.write("**Take your shortlist with you**")
        st.caption("Metadata only. Uploaded source paths are never exposed or copied.")
        all_rows = session.ranking["selected"]
        ids = [r["photo_id"] for r in all_rows]
        selected = st.multiselect(
            "Export photos",
            ids,
            default=ids,
            format_func=lambda i: session.rows[i]["metadata"]["filename"],
        )
        rows = [r for r in all_rows if r["photo_id"] in selected]
        for fmt in ("json", "csv"):
            st.download_button(
                f"Download {fmt.upper()} manifest",
                export_manifest(rows, session.rows, names, session.decisions, fmt),
                file_name=f"photocull-demo-shortlist.{fmt}",
                key=f"export-{fmt}",
                mime="application/json" if fmt == "json" else "text/csv",
            )
        st.caption("Nothing is moved, overwritten or deleted.")


def main():
    st.set_page_config(
        page_title="PhotoCull · Web Demo",
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    embed = st.query_params.get("compact", "").lower() == "true"
    apply_style(embed)
    start_cleanup()
    try:
        previous = st.session_state.get("demo_session")
        session = REGISTRY.acquire(previous)
        if previous is not None and previous.closed:
            st.info("Your temporary session expired and was cleared.")
        st.session_state["demo_session"] = session
    except DemoBusyError as exc:
        st.info(str(exc))
        st.stop()
    if not embed:
        st.html('<p class="pc-eyebrow">◈ PhotoCull &nbsp; / &nbsp; Web Demo</p>')
    if not session.photos:
        left, right = st.columns([1.3, 1])
        with left:
            st.html(
                '<div class="pc-hero"><h1>Keep the moments.<br>Lose the repetition.</h1>'
                "<p>Find duplicate shots, spot technical issues, organize photo events, "
                "and curate stronger shortlists with computer vision.</p></div>"
            )
        with right:
            demo = bundled_sources()
            st.image(
                demo[0].data,
                caption="Generated demo illustration · no personal photos",
                width="stretch",
            )
        primary, secondary = st.columns(2)
        if primary.button("Upload Photos", type="primary", width="stretch"):
            st.session_state["show_upload"] = True
        if secondary.button("Try Demo Without Uploading Photos", width="stretch"):
            try:
                with st.spinner("Exploring the generated demo"):
                    add_sources(session, bundled_sources())
                st.session_state["demo_notice"] = True
                st.rerun()
            except (DemoLimitError, DemoBusyError, MemoryError):
                st.warning("The demo is busy or out of resources. Clear this session and retry.")
    st.caption(PRIVACY)
    st.caption(
        "Images leave your browser for this server. No remote inference, accounts or telemetry."
    )
    if st.session_state.get("demo_notice") and session.photos:
        st.success(
            "You're exploring generated, public-safe illustrations. Try a real upload or "
            "inspect the duplicate, event and shortlist explanations."
        )
    if st.session_state.get("show_upload") or session.photos:
        with st.expander("Add photos · one image at a time", expanded=not session.photos):
            st.caption(
                "Up to 30 images · 15 MiB/image · 60 MiB total · 8 megapixels/image. "
                "Sequential uploads keep server buffers bounded."
            )
            generation = st.session_state.get("upload_generation", 0)
            upload = st.file_uploader(
                "Choose a JPEG, PNG or WEBP image",
                type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=False,
                max_upload_size=15,
                key=f"upload-{generation}",
                disabled=len(session.photos) >= 30,
            )
            if st.button(
                "Analyze and add photo",
                disabled=upload is None or len(session.photos) >= 30,
                type="primary",
            ):
                try:
                    # This adapter alone knows Streamlit UploadedFile; CV services receive bytes.
                    with st.spinner("Analyzing your image"):
                        session.add(UploadedImageSource(upload.name, upload.getbuffer()))
                        session.analyze()
                    st.session_state["upload_generation"] = generation + 1
                    st.rerun()
                except (DemoLimitError, DemoBusyError) as exc:
                    st.warning(str(exc))
                except MemoryError:
                    st.warning("Memory is limited. Try a smaller image or clear this session.")
                except Exception:
                    st.warning("Temporary processing error. Your other photos are still available.")
    for message in session.failures[-5:]:
        st.warning(message)
    if session.photos:
        if st.button("Refresh results"):
            try:
                session.analyze()
            except (DemoBusyError, MemoryError):
                st.warning("The demo is busy or out of memory. Retry shortly.")
            except Exception:
                st.warning("Temporary processing error. Your photos remain available.")
        st.caption(
            f"{len(session.photos)} / {MAX_IMAGES} images · "
            f"{session.total_upload_bytes / 1024 / 1024:.1f} / "
            f"{MAX_TOTAL_BYTES / 1024 / 1024:.0f} MiB upload budget"
        )
        result_views(session)
    if st.button("Clear temporary session", key="clear-session"):
        REGISTRY.release(session)
        del st.session_state["demo_session"]
        st.session_state["upload_generation"] = st.session_state.get("upload_generation", 0) + 1
        st.session_state["demo_notice"] = False
        st.rerun()
    if not embed:
        left, right = st.columns(2)
        left.html(
            '<div class="pc-mode"><h3>Web Demo</h3><p>A temporary upload session. '
            "Small collections, shared CPU, no permanent photo or preference storage.</p></div>"
        )
        right.html(
            '<div class="pc-mode"><h3>Local Edition</h3><p>Your photos remain on your device. '
            "Full-folder analysis, reusable cache, persistent decisions "
            "and private learning.</p></div>"
        )
        st.html(
            '<p class="pc-footer">Built for thoughtful review. Nothing is deleted. '
            "Optional models stay local. Personalization remains experimental.</p>"
        )


if __name__ == "__main__":
    main()
