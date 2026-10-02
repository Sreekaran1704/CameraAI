# Phase 2 evaluation and private benchmark guide

`synthetic_duplicates_v1` uses development seed families 1704..1715 and held-out 81704..81715.
Each split has 206 images and 163 labeled pairs: 12 exact, 84 near, 24 burst same-moment,
31 similar non-duplicates and 12 unrelated. Transformations include JPEG recompression, resizing,
slight/moderate crop, brightness, contrast, rotation and blur. Hard negatives cover same-tone
unrelated graphics, walls, darkness, sky, sunsets, screenshots, documents and repeated patterns.
These are generated geometric scenes, not natural-photo semantic judgments.

Development and held-out seed families are separate. Loader validation rejects family leakage,
byte-identical content across splits, unknown references and conflicting pair labels. A repeated
negative-pattern generator initially produced byte-identical examples across splits; it was fixed
before the final report, without retuning the frozen thresholds. The image checksum and label
checksum in reports identify the final dataset. Related nonidentical edits still require curator
family labels; automatic validation cannot prove all capture families independent.

## Selection

Development-only verification experiment at pHash≤6:

| Pixel correlation | Precision | Recall | False positives |
| --- | ---: | ---: | ---: |
| 0.95 | 82.4% | 89.3% | 16 |
| 0.98 | 83.3% | 83.3% | 14 |
| 0.99 | 85.9% | 72.6% | 10 |
| 0.995 | 88.2% | 71.4% | 8 |
| 0.999 | 100% | 71.4% | 0 |

The stricter guard rejects subtle moving burst frames. With that guard fixed, pHash thresholds
0/2/4/6/8/10/12 were compared. Threshold 0 gave 100% precision and 57.1% recall; thresholds ≥2
gave 100% precision and 71.4% recall. Choose 2 as the smallest achieving maximal development recall
with observed precision≥98%. Burst windows 2/5/10 seconds gave pair-rule recall 0%/100%/100%; choose 5.
The CLI reports a suggested operating point and never silently rewrites application configuration.

## Final held-out results

| Detector/metric scope | TP / FP / FN / TN | Precision | Recall | F1 | FPR |
| --- | --- | ---: | ---: | ---: | ---: |
| Exact grouping | 12 / 0 / 0 / 151 | 100% | 100% | 100% | 0% |
| Near pair rule | 60 / 1 / 24 / 66 | 98.36% | 71.43% | 82.76% | 1.49% |
| Near final groups | 60 / 0 / 24 / 67 | 100% | 71.43% | 83.33% | 0% |
| Burst pair rule | 24 / 0 / 0 / 127 | 100% | 100% | 100% | 0% |
| Burst final groups | 12 / 0 / 12 / 127 | 100% | 50% | 66.67% | 0% |

Pair-rule scores compare labeled pairs directly. Final-group scores count a pair only when both
members occur in the same emitted group, and include candidate-generation/grouping effects. Near
and burst metrics exclude exact-copy labels, which have a separate detector. Unknown/unlabeled
pairs are not counted as negatives. Zero predictions yield null precision, not perfect precision.
Labels distinguish duplicate edits from distinct burst captures; classification precision is
therefore tested against meaningful pose/content changes. Final complete-link burst groups retain
only 0–3-second or 3–7-second pairs; the full 7-second span exceeds the selected 5-second window.

These are small curated labeled-pair subsets, not exhaustive all-pairs ground truth. A final group's
100% observed precision does not establish zero false positives in unlabelled pairs or real photos.
False recommendations are more dangerous than missed duplicates. No deletion recommendations or
actions are exposed; users review alternatives themselves. **The requested 96% precision / 89%
recall statement is not supported by this benchmark and is not used as a product accuracy claim.**

## False-positive and missed-match analysis

One held-out near-rule false positive: held_out-11-burst1 ↔ held_out-11-burst2. pHash 0, dHash 2,
aHash 0, correlation 0.9990826, capture gap 4 seconds. The moving shape is subtle enough to fool
the strict pixel rule. Its pair did not survive the final group partition, but the classifier error
is still reported; thresholds were not retuned after seeing it. All measured hard-negative category
pairs were rejected. That does not establish safety on real skies/sunsets/documents.

There are 24 near false negatives, mainly crop/rotation transformations. High-correlation gates
and low-texture guards trade recall for conservative suggestions. Future improvements need more
privately labeled hard cases rather than raising a threshold to match a desired headline number.

Full IDs and similarity measurements: benchmarks/phase2-evaluation.json and phase2-measurements.csv.
Development loose-rule false positives: benchmarks/development-diagnostics.json. All remain local.

## Private manifests

```json
{
  "dataset_version": "private_duplicates_v1",
  "photos": [
    {"id": "dev-a", "path": "photos/a.jpg", "split": "development", "family": "capture-001"},
    {"id": "dev-b", "path": "photos/b.jpg", "split": "development", "family": "capture-001"},
    {"id": "test-a", "path": "photos/c.jpg", "split": "held_out", "family": "capture-101"},
    {"id": "test-b", "path": "photos/d.jpg", "split": "held_out", "family": "capture-101"}
  ],
  "pairs": [
    {"a": "dev-a", "b": "dev-b", "label": "NEAR_DUPLICATE", "split": "development"},
    {"a": "test-a", "b": "test-b", "label": "NEAR_DUPLICATE", "split": "held_out"}
  ]
}
```

Use all five supported labels. Include representative negatives and enough independent families;
the tiny example above illustrates schema only and cannot establish meaningful performance.
Paths are local and resolved relative to the manifest (absolute paths also work). Optional capture_time,
capture_timezone and filesystem_time override EXIF for curated timestamp tests. Filesystem times
are otherwise omitted in evaluation to avoid creation-time artifacts. A `groups` array may provide
objects with members, label and split; the harness expands bounded groups (≤256 members) to pairs.
Equivalent labels deduplicate; conflicting labels are refused. Group labels describe every member
pair, so do not use a burst group whose endpoints fall outside the chosen ground-truth moment.

```sh
.venv/bin/photocull evaluate-duplicates --manifest /private/path/manifest.json
.venv/bin/photocull evaluate-duplicates --manifest /private/path/manifest.json --format csv
.venv/bin/python benchmarks/inspect_development.py /private/path/manifest.json
```

Use private consented/licensed local photos; never commit them or their filenames by default.
Reports contain dataset/model/configuration identities, raw measurements, confusion counts and
selected parameters. No network/model download is used. Frozen held-out sets must not be used
to retune rules; collect a fresh holdout after substantive rule changes.
