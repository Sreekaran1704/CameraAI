"""Local PhotoCull interface. All media comes from derived thumbnails."""

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import streamlit as st

from photocull.cache import Cache, refuse_symlinks
from photocull.config import load_config
from photocull.jobs import recover_interrupted, start_job
from photocull.storage import Repository
from photocull.ui.style import apply_style

st.set_page_config(page_title="PhotoCull · Local photo analysis", page_icon="◈", layout="wide")

apply_style()
st.title("PhotoCull")
st.caption("Your photos stay on this device. · Local Edition · Private camera roll intelligence")


def config():
    import os

    return load_config(
        path=Path(os.environ["PHOTOCULL_CONFIG"]) if "PHOTOCULL_CONFIG" in os.environ else None,
        cache_dir=Path(os.environ["PHOTOCULL_CACHE_DIR"])
        if "PHOTOCULL_CACHE_DIR" in os.environ
        else None,
    )


try:
    settings = config()
    cache = Cache(settings.cache_dir)
except (ValueError, OSError) as exc:
    st.error(str(exc))
    st.stop()

with st.sidebar:
    st.header("Local workspace")
    page = st.radio(
        "Page",
        ["Import", "Overview", "Duplicate Review", "Events", "Best Photos", "Preferences", "Cache"],
    )
    st.caption("JPG / JPEG · PNG · WEBP")
    st.caption("Your photos remain on your device. No uploads or photo deletion.")
    with st.expander("Feature status"):
        from photocull.embeddings import model_status

        st.caption("Hash duplicates · ready | Time events · ready | Generic ranking · ready")
        for identifier, status in model_status(cache).items():
            st.caption(f"{identifier}: {status['status']}")
        st.caption("Optional checkpoints never download at startup.")
    with st.expander("Analysis Settings"):
        model = st.selectbox(
            "Local embeddings",
            ["disabled", "mobilenet", "tinyclip"],
            index=["disabled", "mobilenet", "tinyclip"].index(settings.embeddings.model),
            format_func=lambda m: {
                "disabled": "Disabled · frozen hash baseline",
                "mobilenet": "MobileNetV3 Small",
                "tinyclip": "TinyCLIP ViT-8M/16",
            }[m],
        )
        settings = replace(settings, embeddings=replace(settings.embeddings, model=model))
        st.caption(
            "Applies to the next analysis or Recalculate groups. Models never download "
            "during scans. Missing weights use hash-only analysis."
        )
        if model != "disabled":
            st.warning(
                "Experimental: expanded hard negatives fell below the precision target. "
                "Hash-only remains the recommended default; inspect every recovered pair."
            )
            st.code(f"photocull --cache-dir {cache.root} model-setup {model}")

        event_model = st.selectbox(
            "Event discovery",
            ["disabled", "mobilenet", "tinyclip"],
            index=["disabled", "mobilenet", "tinyclip"].index(settings.events.model),
            format_func=lambda m: {
                "disabled": "Time only · recommended",
                "mobilenet": "Time + MobileNet · experimental",
                "tinyclip": "Time + TinyCLIP · experimental",
            }[m],
        )
        settings = replace(
            settings,
            events=replace(
                settings.events,
                method="time" if event_model == "disabled" else "dbscan",
                model=event_model,
                time_weight=(
                    settings.events.time_weight
                    if event_model == "disabled"
                    else 0.3
                    if event_model == "tinyclip"
                    else 0.1
                ),
                visual_weight=(
                    settings.events.visual_weight
                    if event_model == "disabled"
                    else 0.7
                    if event_model == "tinyclip"
                    else 0.9
                ),
                epsilon=settings.events.epsilon if event_model == "disabled" else 0.15,
            ),
        )
        st.caption(
            "Event features are independent of duplicate detection. "
            "Requires local model setup and optional event dependencies."
        )
        if event_model != "disabled":
            st.code(f"photocull --cache-dir {cache.root} model-setup {event_model}")


def recent_runs():
    repo = Repository(cache.root / "metadata.db")
    try:
        recover_interrupted(repo)
        return repo.runs()
    finally:
        repo.close()


def select_run():
    runs = recent_runs()
    if not runs:
        st.info("Choose a local folder on Import to begin.")
        return None
    identifiers = [run["id"] for run in runs]
    labels = {
        run["id"]: f"{datetime.fromisoformat(run['started_at']).astimezone():%Y-%m-%d %H:%M:%S %Z}"
        f" · {run['status']} · {run['source_root']}"
        for run in runs
    }
    chosen = st.session_state.get("active_run")
    return st.selectbox(
        "Analysis history",
        identifiers,
        index=identifiers.index(chosen) if chosen in identifiers else 0,
        format_func=labels.get,
    )


@st.fragment(run_every="1s")
def progress_panel(run_id):
    repo = Repository(cache.root / "metadata.db")
    try:
        recover_interrupted(repo)
        run = repo.get_run(run_id)
        progress = json.loads(run["progress_json"])
        st.write(f"Status: **{run['status']}** · {progress.get('stage', 'waiting')}")
        total = progress.get("supported_files", 0)
        if total:
            st.progress(min(progress.get("processed", 0) / total, 1))
        fields = (
            ("Discovered photos", "discovered_photos"),
            ("Supported files", "supported_files"),
            ("Unsupported files", "unsupported_files"),
            ("Failures", "failures"),
        )
        for column, (label, key) in zip(st.columns(4), fields, strict=True):
            column.metric(label, progress.get(key, 0))
        st.caption(
            f"Processed: {progress.get('processed', 0)} · "
            f"Skipped symlinks: {progress.get('skipped_symlinks', 0)} · "
            f"Source size: {progress.get('total_source_bytes', 0) / 1e6:.2f} MB"
        )
        if run["status"] in {"queued", "running"}:
            if st.button("Cancel between files", key=f"cancel-{run_id}"):
                repo.cancel(run_id)
        if run["status"] == "interrupted":
            st.warning(
                "Worker was interrupted. Start a new analysis of this folder to reuse "
                "completed results."
            )
        failures = repo.failures(run_id)
        if failures:
            with st.expander("Processing failures", expanded=False):
                st.dataframe(failures, hide_index=True)
    finally:
        repo.close()


if page == "Import":
    st.subheader("Analyze a photo folder")
    st.write("Read-only analysis of local files. Originals remain unchanged.")
    folder = st.text_input("Absolute folder path", placeholder="/Users/you/Pictures/camera-roll")
    thorough = st.checkbox("Thorough rescan", help="Recompute even when file size and mtime match.")
    if st.button("Start local analysis", type="primary", disabled=not folder):
        try:
            st.session_state["active_run"] = start_job(
                Path(folder).expanduser(), settings, thorough
            )
        except (ValueError, OSError) as exc:
            st.error(str(exc))
    run_id = select_run()
    if run_id:
        progress_panel(run_id)

elif page == "Overview":
    st.subheader("Technical Quality Indicators")
    st.caption(
        "Measured indicators can flag intentional blur, darkness, or minimal scenes. "
        "They do not measure artistic quality."
    )
    run_id = select_run()
    if run_id:
        progress_panel(run_id)
        repo = Repository(cache.root / "metadata.db")
        try:
            rows = repo.results(run_id)
            run = repo.get_run(run_id)
        finally:
            repo.close()
        valid = [r for r in rows if r["quality"] and not r["source_changed_since_run"]]
        progress = json.loads(run["progress_json"])
        blur = sum("low_sharpness" in json.loads(r["quality"]["warnings_json"]) for r in valid)
        exposure = sum(
            bool({"underexposure", "overexposure"} & set(json.loads(r["quality"]["warnings_json"])))
            for r in valid
        )
        for col, label, value in zip(
            st.columns(4),
            ["Photos analyzed", "Blur warnings", "Exposure warnings", "Full cache hits"],
            [len(valid), blur, exposure, progress.get("cache_hits", 0)],
            strict=True,
        ):
            col.metric(label, value)
        st.caption("Use Refresh to load newly completed results while an analysis is running.")
        st.button("Refresh results")
        if valid:
            bins = {f"{i / 10:.1f}–{(i + 1) / 10:.1f}": 0 for i in range(10)}
            names = list(bins)
            for row in valid:
                bins[names[min(int(row["quality"]["technical_quality_v1"] * 10), 9)]] += 1
            st.bar_chart(
                {"Technical Quality v1": names, "Photos": list(bins.values())},
                x="Technical Quality v1",
                y="Photos",
                height=220,
                sort=False,
            )
            table = []
            for row in valid:
                meta, quality = row["metadata"], row["quality"]
                table.append(
                    {
                        "Filename": meta["filename"],
                        "Width": meta["width"],
                        "Height": meta["height"],
                        "Megapixels": meta["width"] * meta["height"] / 1e6,
                        "Technical Quality v1": quality["technical_quality_v1"],
                        "Technical Warnings": ", ".join(json.loads(quality["warnings_json"])),
                    }
                )
            st.dataframe(table, hide_index=True, width="stretch")
            selected = st.selectbox(
                "Inspect measurements",
                range(len(valid)),
                format_func=lambda i: valid[i]["metadata"]["filename"],
            )
            row = valid[selected]
            left, right = st.columns([1, 2])
            thumb = row["thumbnail"]
            if thumb:
                try:
                    path = refuse_symlinks(Path(thumb["path"]))
                    if path.parent == cache.root / "thumbnails" and path.is_file():
                        left.image(str(path))
                except ValueError:
                    left.warning("Unsafe thumbnail path refused.")
            right.write(f"Technical Quality v1: **{row['quality']['technical_quality_v1']:.3f}**")
            right.write(
                "Technical Warnings: "
                + (", ".join(json.loads(row["quality"]["warnings_json"])) or "None")
            )
            right.json({"normalized": json.loads(row["quality"]["normalized_json"])})
            with right.expander("Raw measurements and provenance"):
                st.json(
                    {
                        "raw": json.loads(row["quality"]["raw_json"]),
                        "algorithm": "technical_quality_v1",
                        "analysis_id": row["quality"]["analysis_id"],
                        "fingerprint": row["quality"]["fingerprint"],
                        "generated_at": row["quality"]["generated_at"],
                        "hashes": row["hashes"],
                    }
                )
        st.write("Pipeline timing (seconds)")
        st.json(progress.get("timings", {}))
        if any(r["source_changed_since_run"] for r in rows):
            st.warning("Some sources have changed since this run; rescan for current results.")

elif page == "Duplicate Review":
    from photocull.ui.duplicate_review import render_duplicate_review

    run_id = select_run()
    if run_id:
        render_duplicate_review(settings, cache, run_id)

elif page == "Events":
    from photocull.ui.event_review import render_events

    run_id = select_run()
    if run_id:
        render_events(settings, cache, run_id)

elif page == "Best Photos":
    from photocull.ui.best_photos import render_best_photos

    run_id = select_run()
    if run_id:
        render_best_photos(settings, cache, run_id)

elif page == "Preferences":
    from photocull.ui.preferences import render_preferences

    run_id = select_run()
    if run_id:
        render_preferences(settings, cache, run_id)


else:
    st.subheader("Local cache")
    status = cache.status()
    st.metric("Derived cache", f"{sum(status['derived_bytes'].values()) / 1024**2:.1f} MiB")
    st.caption(
        f"Total storage (models/database included): {status['total_bytes'] / 1024**2:.1f} MiB"
    )
    with st.expander("Cache details"):
        st.json(status)
    st.write(
        "Clear Derived Cache removes thumbnails, technical measurements and perceptual "
        "hashes, embeddings, duplicate/burst results, and automatic events, and ranking results. "
        "Source records, scan history, manual events, decisions and "
        "Not Duplicate corrections are preserved."
    )
    if st.button("Clear Derived Cache"):
        repo = Repository(cache.root / "metadata.db")
        try:
            cache.clear_derived(repo)
            st.success("Derived cache cleared. Original photos were not modified.")
        except (ValueError, OSError) as exc:
            st.error(str(exc))
        finally:
            repo.close()

    st.divider()
    st.write("**Reset learned preferences**")
    st.caption(
        "Removes preference choices/model only. Analysis, favorites, manual events and "
        "original photos remain."
    )
    confirmed_preferences = st.checkbox("Confirm preference reset", key="cache-pref-confirm")
    if st.button("Reset My Learned Preferences", disabled=not confirmed_preferences):
        from photocull.preference_storage import PreferenceStore

        repo = Repository(cache.root / "metadata.db")
        try:
            PreferenceStore(repo).reset()
            st.success("Learned preferences reset. Originals and analysis remain.")
        finally:
            repo.close()
