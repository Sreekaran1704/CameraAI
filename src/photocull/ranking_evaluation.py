"""Authored synthetic preference rubrics, split before scoring. No human accuracy claims."""

import json
import resource
import sys
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from itertools import combinations
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from photocull.config import RankingConfig, parameter_hash
from photocull.duplicate_evaluation import scene
from photocull.hashing import PerceptualHashService
from photocull.quality import QualityAnalyzer
from photocull.ranking import rank, shortlist
from photocull.similarity import PhotoFeatures

CATEGORIES = (
    "ordinary",
    "low_light",
    "intentional_blur",
    "bad_outlier",
    "coverage",
    "boring_center",
)


def generate(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if any(folder.iterdir()):
        raise ValueError("Ranking fixture directory must be empty")
    families = []
    for split, seed in (("dev", 51704), ("test", 101704)):
        for index in range(24):
            identifier = f"{split}-{index:02d}"
            category = CATEGORIES[index % len(CATEGORIES)]
            rows, groups = [], []
            for region in range(3):
                base = scene(seed + index * 11 + region)
                variants = {
                    "preferred": base,
                    "soft": base.filter(ImageFilter.GaussianBlur(2)),
                    "dark": ImageEnhance.Brightness(base).enhance(0.25),
                }
                members = []
                for name, image in variants.items():
                    photo_id = f"{identifier}-{region}-{name}"
                    path = folder / f"{photo_id}.png"
                    image.save(path)
                    relevant = 3 if name == "preferred" else 1 if name == "soft" else 0
                    favorite = name == "preferred"
                    if category == "low_light" and region == 0:
                        relevant = 3 if name == "dark" else 2
                        favorite = name == "dark"
                    if category == "intentional_blur" and region == 1:
                        relevant = 3 if name == "soft" else 2
                        favorite = name == "soft"
                    rows.append(
                        {
                            "id": photo_id,
                            "path": path.name,
                            "relevance": relevant,
                            "favorite": favorite,
                            "region": str(region),
                            "timestamp_minutes": region * 70 + len(members),
                            "rubric": (
                                "Prefer intact scene coverage; contextual exceptions are authored"
                            ),
                        }
                    )
                    members.append(photo_id)
                groups.append({"type": "NEAR_DUPLICATE", "members": members})
            # Unrelated noise stresses uniqueness without inventing emotional inference.
            noise = np.random.default_rng(seed + index).integers(
                0, 256, (256, 256, 3), dtype=np.uint8
            )
            image = Image.fromarray(noise)
            noise_id = identifier + "-outlier"
            image.save(folder / f"{noise_id}.png")
            rows.append(
                {
                    "id": noise_id,
                    "path": f"{noise_id}.png",
                    "relevance": 0,
                    "favorite": False,
                    "region": "outlier",
                    "timestamp_minutes": 15,
                    "rubric": "Unrelated noise should not displace scene coverage",
                }
            )
            context = "duplicate" if index < 4 else "burst" if index < 8 else "event"
            if context != "event":
                rows = rows[:3]
                groups = groups[:1]
            families.append(
                {
                    "id": identifier,
                    "split": split,
                    "category": category,
                    "photos": rows,
                    "groups": groups,
                    "context": context,
                }
            )
    manifest = {
        "version": "ranking_fixture_v2",
        "families": families,
        "label_source": (
            "Authored transformation preferences before algorithm output; not a human study"
        ),
        "split_unit": "entire source-scene family",
        "seeds": [51704, 101704],
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def load(manifest_path):
    from photocull.config import QualityConfig

    manifest = json.loads(Path(manifest_path).read_text())
    cases = []
    for family in manifest["families"]:
        photos = []
        for row in family["photos"]:
            path = Path(manifest_path).parent / row["path"]
            with Image.open(path) as image:
                quality = QualityAnalyzer(QualityConfig()).analyze(image)
                hashes = PerceptualHashService().analyze(image)
            fp = parameter_hash(
                {"bytes": __import__("hashlib").sha256(path.read_bytes()).hexdigest()}
            )
            capture = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(minutes=row["timestamp_minutes"])
            photos.append(
                PhotoFeatures(
                    row["id"],
                    fp,
                    fp,
                    256,
                    256,
                    path.stat().st_size,
                    hashes,
                    quality,
                    capture.isoformat(),
                )
            )
        cases.append((family, photos))
    return manifest, cases


def score(family, ranked, selected, k):
    labels = {r["id"]: r for r in family["photos"]}
    predicted = selected[:k]
    ideal = sorted((r["relevance"] for r in labels.values()), reverse=True)[:k]
    dcg = sum(
        (2 ** labels[r["photo_id"]]["relevance"] - 1) / np.log2(i + 2)
        for i, r in enumerate(predicted)
    )
    idcg = sum((2**rel - 1) / np.log2(i + 2) for i, rel in enumerate(ideal))
    relevant = {i for i, r in labels.items() if r["relevance"] >= 2}
    favorites = {i for i, r in labels.items() if r["favorite"]}
    ids = {r["photo_id"] for r in predicted}
    positions = {r["photo_id"]: i for i, r in enumerate(ranked)}
    correct = total = 0
    for a, b in combinations(labels, 2):
        if labels[a]["relevance"] == labels[b]["relevance"]:
            continue
        total += 1
        correct += (positions[a] < positions[b]) == (
            labels[a]["relevance"] > labels[b]["relevance"]
        )
    seen, redundant = set(), 0
    groups = {i: j for j, g in enumerate(family["groups"]) for i in g["members"]}
    for row in predicted:
        moment = groups.get(row["photo_id"], row["photo_id"])
        redundant += moment in seen
        seen.add(moment)
    regions = {labels[i]["region"] for i in ids & relevant}
    true_regions = {r["region"] for r in labels.values() if r["relevance"] >= 2}
    return {
        "ndcg": float(dcg / idcg) if idcg else 0,
        "precision_at_k": len(ids & relevant) / k,
        "recall_at_k": len(ids & relevant) / len(relevant) if relevant else 0,
        "favorite_recall": len(ids & favorites) / len(favorites) if favorites else 0,
        "mrr": next(
            (1 / (i + 1) for i, r in enumerate(predicted) if r["photo_id"] in favorites), 0
        ),
        "pairwise_accuracy": correct / total if total else 1,
        "redundancy_rate": redundant / len(predicted) if predicted else 0,
        "duplicate_contamination": redundant / len(predicted) if predicted else 0,
        "coverage": len(regions) / len(true_regions) if true_regions else 1,
        "selected": [r["photo_id"] for r in predicted],
        "outlier_selected": any(labels[i]["relevance"] == 0 and "outlier" in i for i in ids),
    }


def evaluate_cases(cases, config, vectors=None):
    output = []
    for family, photos in cases:
        context = family["context"]
        ranked = rank(photos, config, context, vectors)
        k = 1 if context in {"duplicate", "burst"} else 3
        result = shortlist(
            photos,
            ranked["ranked"],
            k,
            config,
            vectors,
            family["groups"],
            {r["id"]: r["region"] for r in family["photos"]},
        )
        output.append(
            {
                "family": family["id"],
                "category": family["category"],
                "context": context,
                "k": k,
                "metrics": score(family, ranked["ranked"], result["selected"], k),
            }
        )
    keys = (
        "ndcg",
        "precision_at_k",
        "recall_at_k",
        "favorite_recall",
        "mrr",
        "pairwise_accuracy",
        "redundancy_rate",
        "duplicate_contamination",
        "coverage",
    )

    def average(rows):
        return {key: float(np.mean([r["metrics"][key] for r in rows])) for key in keys}

    return {
        "metrics": average(output),
        "cases": output,
        "contexts": {
            context: average([r for r in output if r["context"] == context])
            for context in ("duplicate", "burst", "event")
        },
    }


def evaluate(manifest_path, cache_dir=None):
    manifest, cases = load(manifest_path)
    dev = [c for c in cases if c[0]["split"] == "dev"]
    test = [c for c in cases if c[0]["split"] == "test"]
    configs = []
    for q, r, u in ((0.9, 0.1, 0), (0.75, 0.2, 0.05), (0.6, 0.35, 0.05), (0.6, 0.2, 0.2)):
        for penalty in (0, 0.1, 0.25, 0.4):
            for cap in (0.1, 0.25):
                configs.append(
                    RankingConfig(
                        quality_weight=q,
                        representation_weight=r,
                        uniqueness_weight=u,
                        diversity_penalty=penalty,
                        uniqueness_cap=cap,
                    )
                )
    trials = [{"parameters": asdict(c), "dev": evaluate_cases(dev, c)["metrics"]} for c in configs]
    best = max(
        trials,
        key=lambda t: (
            t["dev"]["ndcg"],
            t["dev"]["favorite_recall"],
            t["dev"]["coverage"],
            -t["parameters"]["diversity_penalty"],
        ),
    )
    selected = RankingConfig(**best["parameters"])
    burst_trials = [
        {
            "weight": w,
            "dev": evaluate_cases(dev, replace(selected, burst_quality_weight=w))["contexts"][
                "burst"
            ],
        }
        for w in (0.70, 0.85, 1.0)
    ]
    burst_best = max(burst_trials, key=lambda t: (t["dev"]["ndcg"], t["dev"]["favorite_recall"]))
    selected = replace(selected, burst_quality_weight=burst_best["weight"])
    baseline = replace(selected, variant="A")
    result = {
        "dataset_version": manifest["version"],
        "families": len(cases),
        "photos": sum(len(p) for _, p in cases),
        "label_source": manifest["label_source"],
        "selection": "Development macro NDCG, favorite recall, coverage; lower penalty on ties",
        "trials": trials,
        "burst_trials": burst_trials,
        "selected_parameters": asdict(selected),
        "A": {"dev": evaluate_cases(dev, baseline), "test": evaluate_cases(test, baseline)},
        "B": {"dev": evaluate_cases(dev, selected), "test": evaluate_cases(test, selected)},
        "notes": [
            "Both A/B apply identical hard known-group suppression",
            "Ranking conditional on supplied group labels, not end-to-end duplicate accuracy",
            "K=1 duplicate/burst and K=3 event; macro metrics separate contexts",
            "Favorites used only as evaluation labels; never a score input",
        ],
    }
    global_photos = [p for _, photos in test for p in photos]
    global_groups = [g for family, _ in test for g in family["groups"]]
    global_rows = [r for family, _ in test for r in family["photos"]]
    membership = {r["id"]: family["id"] for family, _ in test for r in family["photos"]}
    combined = {"photos": global_rows, "groups": global_groups}
    result["global_top_k"] = {}
    for variant, cfg in (("A", baseline), ("B", selected)):
        ranked = rank(global_photos, cfg)
        result["global_top_k"][variant] = {}
        for k in (10, 20):
            selected_global = shortlist(
                global_photos, ranked["ranked"], k, cfg, groups=global_groups, coverage=membership
            )
            measured = score(combined, ranked["ranked"], selected_global["selected"], k)
            measured["event_coverage"] = len(
                {membership[r["photo_id"]] for r in selected_global["selected"]}
            ) / len(test)
            relevance_lookup = {r["id"]: r["relevance"] for r in global_rows}
            measured["relevant_event_coverage"] = len(
                {
                    membership[r["photo_id"]]
                    for r in selected_global["selected"]
                    if relevance_lookup[r["photo_id"]] >= 2
                }
            ) / len(test)
            result["global_top_k"][variant][str(k)] = measured
    # Optional existing infrastructure: prepare local benchmark vectors once, then reuse them.
    if cache_dir:
        from PIL import Image

        from photocull.cache import Cache
        from photocull.embeddings import EmbeddingService

        records = []
        for family, photos in cases:
            lookup = {p.id: p for p in photos}
            for row in family["photos"]:
                path = Path(manifest_path).parent / row["path"]

                def loader(path=path):
                    with Image.open(path) as image:
                        return image.copy()

                records.append((row["id"], lookup[row["id"]].fingerprint, loader))
        service = EmbeddingService(Cache(cache_dir), "tinyclip", "cpu", 16)
        vectors, generated = service.encode(records)
        _, reused = service.encode(records)
        result["cached_tinyclip_B"] = {
            "parameters": asdict(selected),
            "dev": evaluate_cases(dev, selected, vectors),
            "test": evaluate_cases(test, selected, vectors),
            "preparation": generated,
            "reuse": reused,
            "note": "Same frozen weights as hash B; diagnostic, not retuned on test",
        }
    return result


def performance(config=None):
    from photocull.event_evaluation import metadata_records

    config = config or RankingConfig()
    output = []
    for count in (30, 100, 500, 1000, 5000):
        photos, vectors = metadata_records(count)
        for variant in ("A", "B"):
            cfg = replace(config, variant=variant)
            ranked = rank(photos, cfg, vectors=vectors)
            selected = shortlist(photos, ranked["ranked"], min(20, count), cfg, vectors)
            output.append(
                {
                    "records": count,
                    "variant": variant,
                    "ranking_seconds": ranked["ranking_seconds"],
                    "shortlist_seconds": selected["shortlist_seconds"],
                    "candidate_count": count,
                    "comparisons": ranked["comparisons"] + selected["selection_comparisons"],
                    "peak_memory_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                    / (2**20 if sys.platform == "darwin" else 1024),
                    "embedding_reuse": "100% preloaded synthetic 64D vectors; no inference",
                }
            )
    return output


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--generate", type=Path)
    parser.add_argument("--performance", action="store_true")
    args = parser.parse_args()
    result = (
        generate(args.generate)
        if args.generate
        else performance()
        if args.performance
        else evaluate(args.manifest, args.cache_dir)
    )
    print(json.dumps(result, allow_nan=False))
