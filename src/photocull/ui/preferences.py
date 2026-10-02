"""Explicit pair choices, corrections, learning progress and local reset."""

import os

import streamlit as st

from photocull.preference_storage import PreferenceStore, consistency
from photocull.preferences import MINIMUM, NAMES, candidates, feature_records
from photocull.ranking_service import prepare
from photocull.storage import Repository
from photocull.ui.event_review import thumbnail


def get_store(repo):
    demo = os.environ.get("PHOTOCULL_WEB_DEMO") == "1" or st.session_state.get(
        "preference_session_only", False
    )
    if demo:
        if "preference_demo_state" not in st.session_state:
            st.session_state["preference_demo_state"] = {}
        return PreferenceStore(state=st.session_state["preference_demo_state"])
    return PreferenceStore(repo)


def render_preferences(settings, cache, scan_id):
    st.subheader("Preferences")
    forced_demo = os.environ.get("PHOTOCULL_WEB_DEMO") == "1"
    demo = st.checkbox(
        "Web Demo · session-only preferences",
        value=forced_demo or st.session_state.get("preference_session_only", False),
        disabled=forced_demo,
    )
    st.session_state["preference_session_only"] = demo
    st.caption(
        "Web Demo stores choices/model only in this browser session. "
        "Local Edition persists privately on this device. No uploads."
    )
    repo = Repository(cache.root / "metadata.db")
    try:
        data = prepare(repo, scan_id, settings)
        # Fixed interpretable hash-derived feature schema, independent of cached model availability.
        data["vectors"] = {}
        records = feature_records(data)
        store = get_store(repo)
        store.allocate(records)
        model = store.model(records)
        feedback = store.feedback()
        examples = store.examples(records)
        st.write("**Teach PhotoCull My Taste**")
        st.caption(
            "Choose by your own taste. Baseline scores are hidden before labeling. "
            "Whole connected events/duplicate/burst groups are reserved before labeling."
        )
        allocation = st.radio(
            "Comparison set", ["Training", "Held-out evaluation"], horizontal=True
        )
        split = "train" if allocation == "Training" else "holdout"
        strategy = st.selectbox(
            "Pair selection",
            ["useful", "uncertainty", "random"],
            format_func=lambda s: {
                "useful": "Context and baseline disagreement",
                "uncertainty": "Uncertain model predictions",
                "random": "Random contextual pairs",
            }[s],
        )
        repeat = st.checkbox("Deliberately repeat an earlier comparison for consistency")
        seen = [e["pair_key"] for e in examples]
        pool = [
            p
            for p in candidates(
                data,
                records,
                () if repeat else seen,
                model if "coefficients" in model else None,
                strategy,
                partition_filter=split,
            )
            if p["partition"] == split and (not repeat or p["key"] in seen)
        ]
        if pool:
            pair = dict(pool[0])
            if len(feedback) % 2:
                pair["a"], pair["b"] = pair["b"], pair["a"]
            st.caption(
                f"{allocation} · {'consistency repeat' if repeat else 'new contextual pair'}"
            )
            for side, col in zip(("a", "b"), st.columns(2), strict=True):
                with col:
                    thumbnail(data["rows"][pair[side]], cache, f"Photo {side.upper()}")
            choice = None
            for label, value, col in zip(
                ("Prefer A", "Prefer B", "No Preference / Tie", "Skip"),
                ("a", "b", "tie", "skip"),
                st.columns(4),
                strict=True,
            ):
                with col:
                    if st.button(label, width="stretch"):
                        choice = value
            if choice:
                store.save(records[pair["a"]], records[pair["b"]], choice, repeat)
                st.rerun()
        else:
            st.info(
                "No unreviewed contextual pairs remain in this set. "
                "Analyze more events or deliberately repeat a choice."
            )
        if st.button("Undo latest choice or correction", disabled=not feedback):
            store.undo()
            st.rerun()
        with st.expander("Review and correct previous choices"):
            if feedback:
                entry_id = st.selectbox(
                    "Previous comparison", [e["id"] for e in reversed(feedback)]
                )
                entry = next(e for e in feedback if e["id"] == entry_id)
                current_choice = any(e["id"] == entry_id for e in examples)
                if not current_choice:
                    st.warning(
                        "This comparison references older source/features and is "
                        "excluded from learning. Current thumbnails are hidden."
                    )
                st.caption(
                    f"Photo A: {entry['a']['photo_id']} · Photo B: {entry['b']['photo_id']} · "
                    f"{entry['partition']} · {'repeat' if entry['repeat'] else 'original'}"
                )
                for side, col in zip(("a", "b"), st.columns(2), strict=True):
                    with col:
                        identifier = entry[side]["photo_id"]
                        if current_choice and identifier in data["rows"]:
                            thumbnail(
                                data["rows"][identifier], cache, f"Previous Photo {side.upper()}"
                            )
                corrected = st.selectbox(
                    "Corrected preference",
                    ["a", "b", "tie", "skip"],
                    index=["a", "b", "tie", "skip"].index(entry["choice"]),
                    format_func=lambda c: {
                        "a": "Prefer A",
                        "b": "Prefer B",
                        "tie": "Tie",
                        "skip": "Skip",
                    }[c],
                )
                if st.button("Save correction"):
                    store.correct(entry_id, corrected)
                    st.rerun()
        st.write("**Learning Progress**")
        collected = model["training_comparisons"]
        st.write(f"{collected} / {MINIMUM} decisive training comparisons")
        st.progress(min(1.0, collected / MINIMUM))
        st.write(
            "Personalized ranking is active (experimental)."
            if model["active"]
            else "Personalization is not active yet."
        )
        st.caption(
            "Activation also requires at least 3 training groups, 10 decisive held-out "
            "pairs in 2 groups, and C accuracy above A and B. Repeats/ties/skips do not train."
        )
        st.caption(
            f"{len(examples)} current choices; {model['excluded_stale_feedback']} stale "
            "choices excluded. Changed source/features invalidate affected training examples."
        )
        if "evaluation" in model:
            st.json(model["evaluation"])
            st.caption(
                "Group bootstrap intervals are descriptive; validation is reused over time, "
                "so later scores are not an untouched final test. Probabilities are uncalibrated."
            )
        st.json(consistency(examples))

        with st.expander("Learning curve on my held-out choices"):
            st.caption(
                "This measures pairwise accuracy only. NDCG and favorite recall need "
                "separate graded photo labels. Validation is reused, not a final blind test."
            )
            if st.button("Compute local learning curve"):
                from photocull.preference_evaluation import learning_curve

                curve = learning_curve(examples)
                rows = [
                    {
                        "comparisons": row["comparisons"],
                        **{v: row["rankings"][v]["pairwise_accuracy"] for v in ("A", "B", "C")},
                    }
                    for row in curve["curve"]
                    if row["available"]
                ]
                if rows:
                    import pandas as pd

                    st.line_chart(pd.DataFrame(rows).set_index("comparisons"))
                    st.json(curve)
                else:
                    st.info(
                        "More decisive training choices across groups and held-out choices "
                        "are needed for a learning curve."
                    )
        st.write("**Learned Preferences**")
        if "coefficients" in model:
            shown = False
            for name, coefficient, stability in zip(
                NAMES, model["coefficients"], model["sign_stability"], strict=True
            ):
                if abs(coefficient) >= 0.15 and stability >= 0.9:
                    shown = True
                    st.write(
                        f"{name}: {coefficient:+.3f} log-odds per training-photo standard "
                        f"deviation; bootstrap sign agreement {stability:.0%}"
                    )
            if not shown:
                st.info("No stable, substantial coefficient tendencies yet.")
            st.caption(
                "Linear associations conditional on all included features, not causes or "
                "universal taste rules. Correlated features can redistribute coefficients."
            )
        else:
            st.info("Collect more decisive choices across independent groups.")
        st.write("**Reset**")
        confirmation = st.checkbox("Confirm removal of my preference choices and learned model")
        if st.button("Reset My Learned Preferences", disabled=not confirmation):
            store.reset()
            st.success(
                "Preferences reset. Photo analysis, manual events, favorites and originals remain."
            )
            st.rerun()
    except (ValueError, OSError) as exc:
        st.error(str(exc))
    finally:
        repo.close()
