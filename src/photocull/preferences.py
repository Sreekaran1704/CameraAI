"""Local, interpretable pairwise preference learning; generic ranking stays frozen."""

import hashlib
import itertools
import math
import time
from dataclasses import replace

import numpy as np

from photocull.config import RankingConfig
from photocull.ranking import rank, shortlist

VERSION = "personalized_ranking_v1"
FEATURE_VERSION = "preference_features_v1"
SEED = 170406
MINIMUM = 50
NAMES = (
    "sharpness",
    "exposure",
    "contrast",
    "resolution",
    "clipping",
    "entropy",
    "noise_proxy",
    "colorfulness",
    "technical_quality_v1",
    "landscape",
    "aspect_ratio",
    "representativeness",
    "uniqueness",
    "redundancy",
    "brightness",
)


def connected_groups(data):
    """Union events AND duplicate/burst components, including transitive overlaps."""
    parent = {p.id: p.id for p in data["photos"]}

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for members in [e["members"] for e in data["events"]["events"]] + [
        g["members"] for g in data["groups"]
    ]:
        members = [str(i) for i in members if str(i) in parent]
        for i in members[1:]:
            a, b = root(members[0]), root(i)
            parent[max(a, b)] = min(a, b)
    components = {}
    for i in parent:
        components.setdefault(root(i), []).append(i)
    return {
        i: hashlib.sha256("|".join(sorted(ids)).encode()).hexdigest()
        for ids in components.values()
        for i in ids
    }


def partition(group, seed=SEED):
    """Stable group allocation made before preference labels are seen."""
    digest = hashlib.sha256(f"{seed}:{group}".encode()).hexdigest()
    return "holdout" if int(digest[:8], 16) % 5 == 0 else "train"


def feature_records(data, config=None):
    """15 scalars; no full embeddings, identity, filename or image content."""
    config = config or RankingConfig()
    by_id = {p.id: p for p in data["photos"]}
    group_ids = connected_groups(data)
    contexts = {e["id"]: e["members"] for e in data["events"]["events"]}
    assigned = {i for members in contexts.values() for i in members}
    for i in by_id.keys() - assigned:
        contexts[f"unassigned:{i}"] = [i]
    output = {}
    for context_id, members in contexts.items():
        photos = [by_id[str(i)] for i in members if str(i) in by_id]
        a = {
            r["photo_id"]: r
            for r in rank(photos, replace(config, variant="A"), vectors=data["vectors"])["ranked"]
        }
        b = rank(photos, replace(config, variant="B"), vectors=data["vectors"])
        for row in b["ranked"]:
            p = by_id[row["photo_id"]]
            raw, norm = p.quality.get("raw", {}), p.quality.get("normalized", {})
            aspect = p.width / max(p.height, 1)
            values = [
                norm.get("sharpness", row["quality"]),
                norm.get("exposure", row["quality"]),
                norm.get("contrast", 0),
                norm.get("resolution", row["quality"]),
                row["clipping"],
                raw.get("entropy_bits", 0) / 8,
                raw.get("noise_residual_mad", 0) / 255,
                raw.get("colorfulness", 0) / 255,
                row["quality"],
                float(aspect >= 1),
                math.log(max(aspect, 1e-6)),
                row["representation"],
                row["uniqueness"],
                1 - row["uniqueness"],
                raw.get("mean_luminance", 0),
            ]
            x = np.asarray(values, dtype=float)
            if not np.isfinite(x).all():
                continue
            output[p.id] = {
                "photo_id": p.id,
                "fingerprint": p.fingerprint,
                "source_versions": p.source_versions,
                "x": x.tolist(),
                "a": a[p.id]["score"],
                "b": row["score"],
                "context": context_id,
                "group": group_ids[p.id],
                "feature_source": b["feature_source"],
            }
    return output


def pair_key(a, b):
    return "|".join(sorted((str(a), str(b))))


def candidates(
    data, records, seen=(), model=None, strategy="useful", limit=2000, partition_filter=None
):
    """Bounded contextual pool. No unrelated singleton comparisons."""
    seen = set(seen)
    pool = {}
    contexts = [(g["members"], 3 if g["type"] == "BURST_GROUP" else 2) for g in data["groups"]] + [
        (e["members"], 1) for e in data["events"]["events"]
    ]
    for members, priority in contexts:
        ids = sorted(str(i) for i in members if str(i) in records)
        # Adjacent score neighbors plus a bounded contextual sample, never O(N²).
        ids.sort(key=lambda i: (records[i]["b"], i))
        pairs = [(ids[i], ids[i + d]) for d in (1, 2, 3) for i in range(len(ids) - d)]
        if len(ids) <= 12:
            pairs.extend(itertools.combinations(ids, 2))
        for a, b in pairs:
            key = pair_key(a, b)
            if key in seen or a == b or records[a]["group"] != records[b]["group"]:
                continue
            aa, bb = records[a], records[b]
            allocation = aa.get("partition", partition(aa["group"]))
            if partition_filter and allocation != partition_filter:
                continue
            disagreement = (aa["a"] - bb["a"]) * (aa["b"] - bb["b"]) < 0
            value = priority + float(disagreement) + (1 - abs(aa["b"] - bb["b"]))
            if model is not None and strategy == "uncertainty":
                value += 4 * (0.5 - abs(probability(model, aa["x"], bb["x"]) - 0.5))
            candidate = {
                "a": min(a, b),
                "b": max(a, b),
                "key": key,
                "priority": value,
                "group": aa["group"],
                "partition": allocation,
            }
            if key not in pool or value > pool[key]["priority"]:
                pool[key] = candidate
    result = sorted(pool.values(), key=lambda p: (-p["priority"], p["key"]))
    if strategy == "random":
        np.random.default_rng(SEED).shuffle(result)
    return result[:limit]


def fit(examples, regularization=1.0):
    """No-intercept L2 logistic model: symmetry P(a>b)=1-P(b>a)."""
    if not np.isfinite(regularization) or regularization <= 0:
        raise ValueError("Regularization must be finite and positive")
    decisive = [e for e in examples if e["choice"] in {"a", "b"} and not e.get("repeat")]
    if not decisive:
        raise ValueError("No decisive training examples")
    unique = {}
    for e in decisive:
        for side in ("a", "b"):
            r = e[side]
            unique[(r["photo_id"], r["fingerprint"])] = r["x"]
    matrix = np.array(list(unique.values()), dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] != len(NAMES) or not np.isfinite(matrix).all():
        raise ValueError("Invalid preference feature vectors")
    scale = np.std(matrix, axis=0)
    scale[scale < 1e-6] = 1
    delta = np.array([(np.array(e["a"]["x"]) - e["b"]["x"]) / scale for e in decisive])
    y = np.array([e["choice"] == "a" for e in decisive], dtype=float)
    w = np.zeros(len(NAMES))
    start = time.perf_counter()
    for _ in range(60):
        z = np.clip(delta @ w, -35, 35)
        p = 1 / (1 + np.exp(-z))
        grad = delta.T @ (p - y) / len(y) + regularization * w / len(y)
        hessian = (delta.T * (p * (1 - p))) @ delta / len(y)
        hessian += np.eye(len(w)) * regularization / len(y)
        step = np.linalg.solve(hessian, grad)
        w -= step
        if np.linalg.norm(step) < 1e-7:
            break
    return {
        "version": VERSION,
        "feature_version": FEATURE_VERSION,
        "features": list(NAMES),
        "scale": scale.tolist(),
        "mean": matrix.mean(axis=0).tolist(),
        "coefficients": w.tolist(),
        "regularization": regularization,
        "seed": SEED,
        "fit_seconds": time.perf_counter() - start,
    }


def utility(model, x):
    return float(
        np.dot(
            (np.asarray(x) - model.get("mean", np.zeros(len(NAMES)))) / model["scale"],
            model["coefficients"],
        )
    )


def probability(model, a, b):
    z = np.clip(utility(model, a) - utility(model, b), -35, 35)
    return float(1 / (1 + np.exp(-z)))


def score(model, record, alpha=None):
    alpha = model.get("alpha", 0.5) if alpha is None else alpha
    learned = float(1 / (1 + np.exp(-np.clip(utility(model, record["x"]), -35, 35))))
    return alpha * record["b"] + (1 - alpha) * learned


def accuracy(examples, scorer):
    examples = [e for e in examples if e["choice"] in {"a", "b"} and not e.get("repeat")]
    if not examples:
        return None
    values = []
    for e in examples:
        difference = scorer(e["a"]) - scorer(e["b"])
        values.append(
            0.5 if abs(difference) < 1e-10 else float((difference > 0) == (e["choice"] == "a"))
        )
    return float(np.mean(values))


def bootstrap_interval(examples, scorer, seed=SEED):
    groups = sorted({e["group"] for e in examples})
    if len(groups) < 2:
        return None
    buckets = {g: [e for e in examples if e["group"] == g] for g in groups}
    rng = np.random.default_rng(seed)
    values = [
        accuracy([e for g in rng.choice(groups, len(groups)) for e in buckets[g]], scorer)
        for _ in range(300)
    ]
    return np.quantile(values, [0.025, 0.975]).tolist()


def metrics(examples, model):
    decisive = [e for e in examples if e["choice"] in {"a", "b"} and not e.get("repeat")]
    scorers = {"A": lambda r: r["a"], "B": lambda r: r["b"], "C": lambda r: score(model, r)}
    result = {
        name: {
            "pairwise_accuracy": accuracy(decisive, scorer),
            "group_bootstrap_95_ci": bootstrap_interval(decisive, scorer),
        }
        for name, scorer in scorers.items()
    }
    # Pairwise choices do not define complete graded relevance/favorites.
    # Do NOT invent NDCG or favorite recall from binary preferences.
    for r in result.values():
        r.update(ndcg=None, favorite_recall=None)
    wins = {}
    for baseline in ("A", "B"):
        buckets = {}
        for e in decisive:
            buckets.setdefault(e["group"], []).append(e)
        differences = [
            accuracy(es, scorers["C"]) - accuracy(es, scorers[baseline]) for es in buckets.values()
        ]
        win, loss = sum(d > 1e-9 for d in differences), sum(d < -1e-9 for d in differences)
        n = win + loss
        p = (
            min(1.0, 2 * sum(math.comb(n, i) for i in range(min(win, loss) + 1)) / 2**n)
            if n
            else None
        )
        wins[baseline] = {
            "group_wins": win,
            "group_losses": loss,
            "group_ties": len(differences) - n,
            "exact_two_sided_sign_p": p if n >= 6 else None,
        }
    return {
        "rankings": result,
        "paired_group_comparison": wins,
        "decisive_pairs": len(decisive),
        "groups": len({e["group"] for e in decisive}),
        "ranking_metrics_limitation": (
            "NDCG/favorite recall require independent graded/favorite labels"
        ),
    }


def train(examples):
    """Nested group development selects alpha/L2; outer holdout never tunes them."""
    decisive = [e for e in examples if e["choice"] in {"a", "b"} and not e.get("repeat")]
    training = [e for e in decisive if e["partition"] == "train"]
    holdout = [e for e in decisive if e["partition"] == "holdout"]
    train_groups = sorted({e["group"] for e in training})
    if set(train_groups) & {e["group"] for e in holdout}:
        raise ValueError("Group leakage between training and holdout")
    train_photos = {(e[s]["photo_id"], e[s]["fingerprint"]) for e in training for s in ("a", "b")}
    test_photos = {(e[s]["photo_id"], e[s]["fingerprint"]) for e in holdout for s in ("a", "b")}
    if train_photos & test_photos:
        raise ValueError("Photo leakage between training and holdout")
    if len(training) < MINIMUM or len(train_groups) < 3:
        return {
            "active": False,
            "reason": "Insufficient training feedback or independent groups",
            "training_comparisons": len(training),
            "minimum": MINIMUM,
        }
    dev_groups = set(train_groups[::4])
    inner = [e for e in training if e["group"] not in dev_groups]
    dev = [e for e in training if e["group"] in dev_groups]
    trials = []
    for reg in (0.1, 1.0, 10.0):
        m = fit(inner, reg)
        for alpha in (0.0, 0.25, 0.5, 0.75, 1.0):
            trials.append(
                (accuracy(dev, lambda r, m=m, alpha=alpha: score(m, r, alpha)), alpha, reg)
            )
    # Ties favor stronger generic prior and stronger regularization.
    _, alpha, reg = max(trials)
    model = fit(training, reg)
    model.update(
        alpha=alpha,
        train_groups=train_groups,
        test_groups=sorted({e["group"] for e in holdout}),
        development_groups=sorted(dev_groups),
        training_comparisons=len(training),
        minimum=MINIMUM,
    )
    evaluation = metrics(holdout, model)
    values = evaluation["rankings"]
    enough = len(holdout) >= 10 and evaluation["groups"] >= 2
    wins = enough and values["C"]["pairwise_accuracy"] > max(
        values["A"]["pairwise_accuracy"], values["B"]["pairwise_accuracy"]
    )
    model.update(
        active=bool(wins),
        evaluation=evaluation,
        reason="Held-out accuracy exceeds both generic baselines"
        if wins
        else (
            "Personalization is not active yet: held-out evidence is insufficient "
            "or C did not improve"
        ),
    )
    # Bootstrap train groups for descriptive sign stability (not causal significance).
    rng = np.random.default_rng(SEED)
    coefficients = []
    for _ in range(30):
        sample = [
            e
            for g in rng.choice(train_groups, len(train_groups))
            for e in training
            if e["group"] == g
        ]
        coefficients.append(fit(sample, reg)["coefficients"])
    c = np.asarray(coefficients)
    model["sign_stability"] = [
        float(np.mean(np.sign(c[:, i]) == np.sign(model["coefficients"][i])))
        for i in range(len(NAMES))
    ]
    return model


def personalized(
    data, config, model, records, members=None, context="event", k=20, scope="library"
):
    """C scores plus unchanged B diversity/suppression policy, or safe generic fallback."""
    ids = set(members) if members is not None else {p.id for p in data["photos"]}
    photos = [p for p in data["photos"] if p.id in ids]
    generic = rank(photos, config.ranking, context, data["vectors"])
    usable = model.get("active") and all(p.id in records for p in photos)
    rows = generic["ranked"]
    if usable:
        rows = [dict(r) for r in rows]
        for row in rows:
            record = dict(records[row["photo_id"]], b=row["score"])
            row["score"] = score(model, record)
            row["preference_score"] = row["score"]
            contributions = (
                (np.asarray(record["x"]) - model.get("mean", np.zeros(len(NAMES))))
                / model["scale"]
                * model["coefficients"]
            )
            strongest = np.argsort(np.abs(contributions))[-3:][::-1]
            row["explanation"] = (
                row["explanation"]
                + [
                    f"Personalized score: {row['score']:.3f}; "
                    f"generic prior weight {model['alpha']:.2f}",
                    "Uncalibrated preference score; not aesthetic certainty",
                ]
                + [
                    f"{NAMES[i]}: standardized linear contribution {contributions[i]:+.3f}"
                    for i in strongest
                ]
            )
        rows.sort(key=lambda r: (-r["score"], r["photo_id"]))
        for i, row in enumerate(rows, 1):
            row["raw_rank"] = i
    coverage = (
        {
            p.id: data["events"]["assignments"].get(p.id, {}).get("event_id") or "unassigned"
            for p in photos
        }
        if scope == "library"
        else None
    )
    selected = shortlist(photos, rows, k, config.ranking, data["vectors"], data["groups"], coverage)
    return {
        **generic,
        **selected,
        "ranked": rows,
        "personalization_active": bool(usable),
        "version": VERSION if usable else generic["version"],
        "personalization_reason": model.get("reason", "Personalization is not active yet."),
    }
