"""Grouped offline evaluation. Simulated preferences NEVER establish human benefit."""

import argparse
import json
import resource
import socket
import time
from itertools import combinations
from pathlib import Path

import numpy as np

from photocull.config import Config
from photocull.preference_storage import PreferenceStore, consistency
from photocull.preferences import (
    MINIMUM,
    SEED,
    accuracy,
    feature_records,
    fit,
    metrics,
    probability,
    score,
)
from photocull.ranking_evaluation import load
from photocull.ranking_service import prepare
from photocull.storage import Repository

COUNTS = (10, 20, 30, 50, 75, 100)


def tuned_fit(training):
    groups = sorted({e["group"] for e in training})
    if len(groups) < 3:
        return None
    dev_groups = set(groups[::4])
    inner = [e for e in training if e["group"] not in dev_groups]
    dev = [e for e in training if e["group"] in dev_groups]
    trials = []
    for reg in (0.1, 1, 10):
        model = fit(inner, reg)
        for alpha in (0, 0.25, 0.5, 0.75, 1):
            trials.append((accuracy(dev, lambda r, m=model, a=alpha: score(m, r, a)), alpha, reg))
    _, alpha, reg = max(trials)
    model = fit(training, reg)
    model["alpha"] = alpha
    return model


def graded_metrics(records, grades, model, k=3):
    """Optional independently labeled photo grades; raw within-group ranking, no MMR."""
    for label in grades.values():
        if type(label.get("relevance")) is not int or not 0 <= label["relevance"] <= 3:
            raise ValueError("Relevance grades must be integers within 0..3")
        if type(label.get("favorite")) is not bool:
            raise ValueError("Favorite labels must be true/false")
    all_groups = {}
    for r in records.values():
        all_groups.setdefault(r["group"], []).append(r)
    groups = {g: rs for g, rs in all_groups.items() if all(r["photo_id"] in grades for r in rs)}
    incomplete = len(all_groups) - len(groups)
    result = {}
    for variant in ("A", "B", "C"):
        ndcg, favorite, correlations = [], [], []
        for rows in groups.values():
            key = (
                (lambda r: score(model, r))
                if variant == "C"
                else (lambda r, v=variant: r[v.lower()])
            )
            ordered = sorted(rows, key=lambda r: (-key(r), r["photo_id"]))
            relevance = [grades[r["photo_id"]]["relevance"] for r in ordered]
            ideal = sorted(relevance, reverse=True)[:k]
            dcg = sum((2**v - 1) / np.log2(i + 2) for i, v in enumerate(relevance[:k]))
            idcg = sum((2**v - 1) / np.log2(i + 2) for i, v in enumerate(ideal))
            ndcg.append(float(dcg / idcg) if idcg else 0)
            favorites = {r["photo_id"] for r in rows if grades[r["photo_id"]]["favorite"]}
            if favorites:
                favorite.append(
                    len(favorites & {r["photo_id"] for r in ordered[:k]}) / len(favorites)
                )
            # Kendall tau-a with grade ties contributing zero, no invented strict preferences.
            concordance = sum(
                np.sign(relevance[i] - relevance[j]) for i, j in combinations(range(len(rows)), 2)
            )
            denominator = len(rows) * (len(rows) - 1) / 2
            if denominator:
                correlations.append(float(concordance / denominator))
        result[variant] = {
            "ndcg_at_k": float(np.mean(ndcg)) if ndcg else None,
            "favorite_recall_at_k": float(np.mean(favorite)) if favorite else None,
            "kendall_tau_a": float(np.mean(correlations)) if correlations else None,
            "groups": len(groups),
            "incomplete_groups_excluded": incomplete,
            "k": k,
        }
    return result


def learning_curve(examples, records=None, grades=None, strategy="random", seed=SEED):
    training = [
        e
        for e in examples
        if e["partition"] == "train" and e["choice"] in {"a", "b"} and not e.get("repeat")
    ]
    holdout = [
        e
        for e in examples
        if e["partition"] == "holdout" and e["choice"] in {"a", "b"} and not e.get("repeat")
    ]
    if {e["group"] for e in training} & {e["group"] for e in holdout}:
        raise ValueError("Group leakage")
    train_photos = {(e[s]["photo_id"], e[s]["fingerprint"]) for e in training for s in ("a", "b")}
    test_photos = {(e[s]["photo_id"], e[s]["fingerprint"]) for e in holdout for s in ("a", "b")}
    if train_photos & test_photos:
        raise ValueError("Photo leakage")
    rng = np.random.default_rng(seed)
    pool = list(training)
    rng.shuffle(pool)
    chosen, rows = [], []
    for count in COUNTS:
        if len(training) < count:
            rows.append({"comparisons": count, "available": False})
            continue
        while len(chosen) < count:
            m = fit(chosen) if strategy == "uncertainty" and len(chosen) >= 10 else None
            if m:
                pool.sort(
                    key=lambda e: (
                        abs(probability(m, e["a"]["x"], e["b"]["x"]) - 0.5),
                        e["pair_key"],
                    )
                )
            chosen.append(pool.pop(0))
        model = tuned_fit(chosen)
        if model is None or not holdout:
            rows.append(
                {
                    "comparisons": count,
                    "available": False,
                    "reason": "Need at least three training groups and holdout choices",
                }
            )
            continue
        row = {
            "comparisons": count,
            "available": True,
            **metrics(holdout, model),
            "alpha": model["alpha"],
            "regularization": model["regularization"],
            "fit_seconds": model["fit_seconds"],
        }
        if records and grades:
            test_groups = {e["group"] for e in holdout}
            test_records = {i: r for i, r in records.items() if r["group"] in test_groups}
            row["graded_ranking"] = graded_metrics(test_records, grades, model)
        rows.append(row)
    return {
        "strategy": strategy,
        "seed": seed,
        "curve": rows,
        "training_groups": sorted({e["group"] for e in training}),
        "holdout_groups": sorted({e["group"] for e in holdout}),
    }


def simulated(manifest):
    _, cases = load(manifest)
    records, examples, grades = {}, [], {}
    for family, photos in cases:
        data = {
            "photos": photos,
            "groups": family["groups"],
            "events": {"events": [{"id": family["id"], "members": [p.id for p in photos]}]},
            "vectors": {},
        }
        rs = feature_records(data)
        split = "train" if family["split"] == "dev" else "holdout"
        # Controlled synthetic taste: brightness/color/detail, dislike noisy unrelated outlier.
        # Defined before fit. NOT a measured user's choices.
        utility = {}
        for i, r in rs.items():
            x = np.array(r["x"])
            utility[i] = float(1.2 * x[1] + 0.8 * x[7] + 0.6 * x[14] - 4 * x[6])
            if "outlier" in i:
                utility[i] -= 2
            records[i] = dict(r, partition=split)
        order = sorted(rs, key=lambda i: (-utility[i], i))
        for i in rs:
            position = order.index(i)
            grades[i] = {
                "relevance": 3 if position < 3 else 2 if position < 6 else 1,
                "favorite": position == 0,
            }
        for a, b in combinations(sorted(rs), 2):
            if abs(utility[a] - utility[b]) < 1e-8:
                continue
            examples.append(
                {
                    "a": rs[a],
                    "b": rs[b],
                    "choice": "a" if utility[a] > utility[b] else "b",
                    "group": rs[a]["group"],
                    "partition": split,
                    "repeat": False,
                    "pair_key": f"{a}|{b}",
                }
            )
    curves = [
        learning_curve(examples, records, grades, strategy, seed)
        for strategy in ("random", "uncertainty")
        for seed in (SEED, SEED + 1, SEED + 2)
    ]
    training = [e for e in examples if e["partition"] == "train"]
    rng = np.random.default_rng(SEED)
    rng.shuffle(training)
    model = tuned_fit(training[:100])
    holdout = [e for e in examples if e["partition"] == "holdout"]
    test_records = {i: r for i, r in records.items() if r["partition"] == "holdout"}
    start = time.perf_counter()
    for r in records.values():
        score(model, r)
    inference = time.perf_counter() - start
    return {
        "label_source": "simulated feature-dependent taste on generated Phase 5 images",
        "human_labels": 0,
        "not_real_user_validation": True,
        "seed": SEED,
        "minimum_candidate": MINIMUM,
        "examples": len(examples),
        "abc": metrics(holdout, model),
        "graded_ranking": graded_metrics(test_records, grades, model),
        "learning_curves": curves,
        "model": model,
        "performance": {
            "fit_seconds_100": model["fit_seconds"],
            "inference_seconds": inference,
            "inference_photos": len(records),
            "model_json_bytes": len(json.dumps(model).encode()),
            "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
        "consistency": {"repeats": 0, "agreement": None},
    }


def noise_experiment(manifest):
    _, cases = load(manifest)
    partitions = {}
    for split in ("dev", "test"):
        pairs = []
        for family, photos in cases:
            if family["split"] != split or family["context"] != "event":
                continue
            noisy = next((p for p in photos if "outlier" in p.id), None)
            detailed = next((p for p in photos if "preferred" in p.id), None)
            if noisy and detailed:
                pairs.append((detailed, noisy))
        partitions[split] = pairs

    def measured(pairs, penalty):
        correct = 0
        for detail, noisy in pairs:

            def value(p):
                q = p.quality
                return q["technical_quality_v1"] - penalty * min(
                    1, q["raw"]["noise_residual_mad"] / 25
                )

            correct += value(detail) > value(noisy)
        return correct / len(pairs) if pairs else None

    trials = [(measured(partitions["dev"], p), -p) for p in (0, 0.25, 0.5, 1, 2)]
    _, negative = max(trials)
    penalty = -negative
    return {
        "version": "technical_quality_noise_guard_experiment_v1",
        "labels": "authored synthetic detail preferred over unrelated random noise",
        "selected_on": "development only",
        "penalty": penalty,
        "formula": "Qv1 - penalty * min(1, noise_residual_mad / 25)",
        "dev_pairs": len(partitions["dev"]),
        "test_pairs": len(partitions["test"]),
        "dev_baseline": measured(partitions["dev"], 0),
        "dev_guard": measured(partitions["dev"], penalty),
        "test_baseline": measured(partitions["test"], 0),
        "test_guard": measured(partitions["test"], penalty),
        "adopted": False,
        "frozen_quality_unchanged": True,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic-manifest", type=Path)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--grades", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    # Evaluation never connects, including image hashing or model fit.
    def deny(*_a, **_k):
        raise RuntimeError("Preference evaluation is offline")

    socket.socket.connect = deny
    socket.socket.connect_ex = deny
    socket.create_connection = deny
    if args.synthetic_manifest:
        result = simulated(args.synthetic_manifest)
        result["noise_experiment"] = noise_experiment(args.synthetic_manifest)
    elif args.cache_dir:
        repo = Repository(args.cache_dir / "metadata.db")
        try:
            runs = repo.runs()
            run = next((r for r in runs if r["status"] == "completed"), None)
            if not run:
                raise ValueError("No completed scan")
            data = prepare(repo, run["id"], Config(cache_dir=args.cache_dir))
            records = feature_records(data)
            store = PreferenceStore(repo)
            examples = store.examples(records)
            grades = json.loads(args.grades.read_text()) if args.grades else None
            model = store.model(records)
            result = {
                "label_source": "explicit local human choices"
                if examples
                else "no human labels available",
                "model": model,
                "feedback_count": len(examples),
                "consistency": consistency(examples),
                "curves": [
                    learning_curve(examples, records, grades, s) for s in ("random", "uncertainty")
                ],
                "preference_database_bytes": args.cache_dir.joinpath("metadata.db").stat().st_size,
            }
        finally:
            repo.close()
    else:
        parser.error("Provide --synthetic-manifest or --cache-dir")
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
