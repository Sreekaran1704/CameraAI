"""Best Photos and event highlights. Export metadata; originals remain untouched."""

from dataclasses import replace

import streamlit as st

from photocull.duplicate_storage import DuplicateStore
from photocull.ranking import export_manifest
from photocull.ranking_service import prepare, recommend
from photocull.storage import Repository
from photocull.ui.event_review import thumbnail


def card(item, data, cache, event_names, key, repo):
    identifier = item["photo_id"]
    with st.container(border=True):
        thumbnail(data["rows"][identifier], cache, data["rows"][identifier]["metadata"]["filename"])
        st.write(f"**Recommended #{item['rank']}** · {event_names.get(identifier, 'Unassigned')}")
        st.caption(f"Technical Quality v1 {item['quality']:.3f} · Relevance {item['score']:.3f}")
        with st.expander("Why recommended"):
            for reason in item["explanation"]:
                st.write(reason)
            for reason in item["weaker_points"]:
                st.caption(reason)
            st.caption("Measured signals do not establish aesthetic or emotional superiority.")
        st.caption(f"Label: {data['decisions'].get(identifier, 'unmarked')}")
        for label, decision in (("Keep", "keep"), ("Favorite", "favorite"), ("Review", "review")):
            if st.button(label, key=f"{key}-{identifier}-{decision}", width="stretch"):
                DuplicateStore(repo).decide(int(identifier), decision)
                st.rerun()


def render_best_photos(settings, cache, scan_id):
    st.subheader("Best Photos")
    st.caption(
        "Explainable recommendations and diverse highlights. Personalized ranking is optional; "
        "generic ranking remains available."
    )
    repo = Repository(cache.root / "metadata.db")
    try:
        data = prepare(repo, scan_id, settings)
        mode = st.radio("Ranking mode", ["Generic", "Personalized"], horizontal=True)
        variant = st.selectbox(
            "Ranking",
            ["B", "A"],
            index=["B", "A"].index(settings.ranking.variant),
            disabled=mode == "Personalized",
            format_func=lambda v: (
                "B · Quality and diversity" if v == "B" else "A · Technical quality"
            ),
        )
        model = st.selectbox(
            "Ranking features",
            ["disabled", "mobilenet", "tinyclip"],
            index=["disabled", "mobilenet", "tinyclip"].index(settings.ranking.model),
            disabled=mode == "Personalized",
            format_func=lambda v: (
                "Perceptual hashes · no inference"
                if v == "disabled"
                else f"Cached {v} vectors only"
            ),
        )
        settings = replace(
            settings, ranking=replace(settings.ranking, variant=variant, model=model)
        )
        if model != "disabled":
            data = prepare(repo, scan_id, settings)
            st.caption(
                f"Existing vector reuse: {data['embedding_reuse']['hits']}/"
                f"{data['embedding_reuse']['requested']}. Missing vectors use hashes "
                "for the entire context. Ranking never computes embeddings."
            )
        view = st.selectbox(
            "View",
            [
                "Best 10",
                "Best 20",
                "Best per Event",
                "Best per Burst",
                "Duplicate representatives",
                "Favorites",
            ],
        )
        event_names = {i: e["name"] for e in data["events"]["events"] for i in e["members"]}
        members, context, k, scope = None, "event", 10 if view == "Best 10" else 20, "library"
        if view == "Best per Event":
            events = data["events"]["events"]
            if not events:
                st.info("Discover events first.")
                return
            choice = st.selectbox(
                "Event", range(len(events)), format_func=lambda i: events[i]["name"]
            )
            event = events[choice]
            members, scope = event["members"], event["id"]
            options = [v for v in (3, 5, 10) if v <= len(members)] or [len(members)]
            k = st.selectbox("Highlights", options)
        elif view in {"Best per Burst", "Duplicate representatives"}:
            context = "burst" if view == "Best per Burst" else "duplicate"
            groups = [
                g for g in data["groups"] if (g["type"] == "BURST_GROUP") == (context == "burst")
            ]
            if not groups:
                st.info("No current groups in this view.")
                return
            choice = st.selectbox(
                "Group", range(len(groups)), format_func=lambda i: f"{groups[i]['type']} {i + 1}"
            )
            members, scope, k = groups[choice]["members"], groups[choice]["signature"], 1
        elif view == "Favorites":
            members = [i for i, decision in data["decisions"].items() if decision == "favorite"]
            scope, k = "favorites", 100
        if mode == "Personalized":
            from photocull.config import RankingConfig
            from photocull.preferences import feature_records, personalized
            from photocull.ui.preferences import get_store

            st.caption("Personalized mode uses the frozen B ranking as its generic prior.")
            settings = replace(settings, ranking=RankingConfig())
            data = prepare(repo, scan_id, settings)
            records = feature_records(data)
            preference_model = get_store(repo).model(records)
            result = personalized(
                data, settings, preference_model, records, members, context, k, scope
            )
            if not result["personalization_active"]:
                st.info("Personalization is not active yet. Using frozen generic Ranking B.")
            st.caption(result["personalization_reason"])
        else:
            result = recommend(repo, settings, data, members, context, k, scope)
        selected = result["selected"]
        if view == "Favorites":
            # This explicit label view must show every favorite, including redundant ones.
            selected = [
                dict(r, rank=i + 1, selection_score=r["score"])
                for i, r in enumerate(result["ranked"])
            ]
        st.caption(
            f"{len(selected)} recommendations · {result['feature_source']} · "
            + (
                "all manually favorited photos"
                if view == "Favorites"
                else "one per known duplicate/burst group"
            )
        )
        if result["shorter_than_requested"] and view != "Favorites":
            st.info("Fewer candidates remain after redundancy suppression; no forced fillers.")
        sort = st.selectbox("Sort by", ["rank", "event", "date", "technical quality"])
        ordered = sorted(
            selected,
            key=lambda r: (
                r["rank"]
                if sort == "rank"
                else event_names.get(r["photo_id"], "")
                if sort == "event"
                else data["rows"][r["photo_id"]]["metadata"].get("capture_time") or ""
                if sort == "date"
                else -r["quality"]
            ),
        )
        with st.expander("Export shortlist manifest"):
            all_ids = [r["photo_id"] for r in selected]
            export_ids = st.multiselect(
                "Export selection",
                all_ids,
                default=all_ids,
                format_func=lambda i: data["rows"][i]["metadata"]["filename"],
            )
            export = [r for r in selected if r["photo_id"] in export_ids]
            for format in ("json", "csv"):
                st.download_button(
                    f"Export {format.upper()} manifest",
                    export_manifest(export, data["rows"], event_names, data["decisions"], format),
                    file_name=f"photocull-shortlist.{format}",
                    mime="application/json" if format == "json" else "text/csv",
                )
            st.caption(
                "Export contains local source paths and metadata; it does not copy or move photos."
            )
        pages = max(1, (len(ordered) + 8) // 9)
        page = st.number_input("Recommendation page", 1, pages, 1)
        for start in range((page - 1) * 9, min(page * 9, len(ordered)), 3):
            for col, item in zip(st.columns(3), ordered[start : start + 3], strict=False):
                with col:
                    card(item, data, cache, event_names, f"best-{scope}", repo)
        with st.expander("Ranking provenance"):
            st.json({k: v for k, v in result.items() if k not in {"ranked", "selected"}})
    except (ValueError, OSError) as exc:
        st.error(str(exc))
    finally:
        repo.close()


def event_highlights(settings, cache, repo, scan_id, members, name):
    data = prepare(repo, scan_id, settings)
    st.write("**Recommended Highlights**")
    options = [v for v in (3, 5, 10) if v <= len(members)] or [len(members)]
    k = st.selectbox("Recommended highlight count", options)
    result = recommend(repo, settings, data, members, k=k, scope=name)
    st.caption("Diverse recommendations, with known duplicate/burst peers suppressed.")
    for start in range(0, len(result["selected"]), 3):
        for col, item in zip(st.columns(3), result["selected"][start : start + 3], strict=False):
            with col:
                thumbnail(
                    data["rows"][item["photo_id"]],
                    cache,
                    f"#{item['rank']} · Quality {item['quality']:.3f}",
                )
                with st.expander("Highlight explanation"):
                    st.write(item["explanation"])
                    st.write(item["weaker_points"])
