"""Development-only diagnostic; never inspect held-out examples during rule design."""

import argparse
import json
from dataclasses import replace
from pathlib import Path

from photocull.config import DuplicateConfig
from photocull.duplicate_evaluation import load_manifest, score_split
from photocull.similarity import SimilarityEngine

parser = argparse.ArgumentParser()
parser.add_argument("manifest", type=Path)
args = parser.parse_args()
manifest, records = load_manifest(args.manifest)
photos = [p for split, p in records if split == "development"]
labels = [p for p in manifest["pairs"] if p["split"] == "development"]
reports = []
for correlation in (0.95, 0.98, 0.99, 0.995, 0.999):
    report = score_split(
        SimilarityEngine(
            replace(DuplicateConfig(), phash_distance=6, verification_correlation=correlation)
        ),
        photos,
        labels,
    )
    reports.append(
        {
            "correlation": correlation,
            "metrics": report["metrics"],
            "false_positives": [
                r
                for r in report["measurements"]
                if r["near"] and r["label"] not in {"NEAR_DUPLICATE", "EXACT_DUPLICATE"}
            ],
        },
    )
print(
    json.dumps(
        {
            "dataset_version": manifest["dataset_version"],
            "phash_distance": 6,
            "development_only": reports,
        },
        indent=2,
    )
)
