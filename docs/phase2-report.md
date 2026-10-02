# PhotoCull Phase 2 completion report

## 1. Implementation summary

Version 0.2.0 adds conservative exact/near duplicate and burst detection, local review decisions,
manual corrections, evaluation and performance CLIs. Existing Phase 1 scanning, quality, hashes,
thumbnails and workers remain the foundation. No new runtime dependencies, embeddings, model
downloads, cloud services or deletion actions were added. No staging, commits or pushes occurred.

## 2. Database/schema changes

Transactional migration 2 preserves Phase 1 data and decisions. Seven new tables store runs,
scan links, useful positive pair evidence, groups, memberships and pair/group corrections.
Algorithm/config identities, source fingerprints, source-analysis versions and timestamps retain
provenance. Derived-cache clearing removes automatic results and preserves corrections.

## 3. Candidate generation

SHA buckets collapse exact copies before a pHash BK-tree metric-radius search. Texture, aspect
and capture-time guards reject cheap mismatches before normalized thumbnail comparisons. There
is no prefix-boundary omission or persisted exhaustive pair matrix. Exact bucketing is linear;
BK-tree search is data-dependent and can degrade toward quadratic behavior. Neighbor, comparison
and group caps bound work and visibly flag incomplete search. Complete-link checks add bounded
within-group work. The path-independent feature engine also supports future in-memory adapters.

## 4. Exact duplicates

Identical streaming SHA-256 file digests group arbitrary numbers of copies, independently of
names. Three 8 MB files yield 16 MB hypothetical savings after retaining one. Metadata-only byte
differences do not qualify as exact. Missing digests do not imply equality.

## 5. Near-duplicate rule

pHash distance ≤2, corroborating dHash/aHash ≤8, absolute log-aspect difference ≤0.04,
entropy ≥3 and contrast ≥25, normalized 32×32 gray correlation ≥0.999 and mean-chroma difference
≤0.12 must agree. Comparable EXIF timestamps more than 60 seconds apart reject the match.
Hashes are not averaged. Dimensions, times, warnings and individual measurements remain inspectable.
Reliability scores are heuristic and uncalibrated. See [methodology](duplicates.md).

## 6. Burst rule

Default maximum time separation is 5 seconds, with pHash ≤12, dHash ≤18, aHash ≤16,
correlation ≥0.70 and log-aspect difference ≤0.15. Timestamp tiers are timezone-aware EXIF,
naive EXIF and optional filesystem fallback; only compatible tiers compare. Filesystem fallback
is disabled by default. Filename sequence is weak evidence only. Bursts imply a shared moment,
not redundant expressions or poses.

## 7. Grouping and chain protection

Deterministic greedy complete-link grouping requires every member pair to pass its relationship
rule. A–B and B–C do not automatically group A–C. Groups store representative, maximum pHash
distance and membership evidence. Complete-link time constraints can split longer bursts.

## 8. Threshold selection

Development-only experiments compared pHash 0/2/4/6/8/10/12, verification correlation
0.95/0.98/0.99/0.995/0.999 and burst windows 2/5/10 seconds. At pHash 6, correlation 0.95
produced 16 false positives; 0.999 produced none. At the selected verification guard, pHash 0
recalled 57.1%; pHash 2–12 recalled 71.4% with 100% development precision. Choose the smallest
threshold achieving that recall at ≥98% precision: 2. Five seconds matched development burst
pairs as well as ten; two seconds missed them. Held-out results did not drive retuning.

## 9. Evaluation dataset

Versioned deterministic geometric scenes use separate seeds and families: 206 images and 163
labeled pairs per development/held-out split. Each split labels 12 exact, 84 near, 24 burst,
31 similar-but-not-duplicate and 12 unrelated pairs. Transformations include JPEG recompression,
resize, slight/moderate crop, brightness, contrast, rotation and blur. Hard negatives include
sunsets, walls, screenshots, dark images, sky, documents and patterns. A fixture byte-leak bug
was fixed before final evaluation without threshold retuning. Family/content checks prevent split
leakage. Private local manifests support manually labeled photos and groups. No private real-photo
labels were provided. Unlabeled pairs are excluded, not treated as negative ground truth.

## 10. Held-out precision/recall/F1

| Relationship/output | TP | FP | FN | Precision | Recall | F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Exact | 12 | 0 | 0 | 100% | 100% | 100% |
| Near pair rules | 60 | 1 | 24 | 98.36% | 71.43% | 82.76% |
| Near final groups | 60 | 0 | 24 | 100% | 71.43% | 83.33% |
| Burst pair rules | 24 | 0 | 0 | 100% | 100% | 100% |
| Burst final groups | 12 | 0 | 12 | 100% | 50% | 66.67% |

Near pair false-positive rate: 1/67 = 1.49%. Group metrics expand final membership into labeled
pairs; they do not establish exhaustive group accuracy. Exact pairs are excluded from near/burst
metrics. These results do not substantiate the suggested 96% precision/89% recall claim.
Full protocol, development tables and interpretation: [evaluation](duplicate-evaluation.md).

## 11. False-positive analysis

The held-out false positive is `held_out-11-burst1` versus `held_out-11-burst2`: different burst
frames, pHash 0, dHash 2, aHash 0, correlation 0.999083, chroma difference 0.005259 and 4-second
separation. It was not placed together in the final near group, but remains a classifier error.
Low-texture/hash collisions motivated the guards. Conservative settings miss slight crops and
rotation variants. False duplicate recommendations are more dangerous than missed duplicates;
review remains necessary. IDs/measurements are retained in JSON/CSV artifacts.

## 12. Representative selection

Highest Technical Quality v1 wins; resolution, sharpness, exposure and stable ID break ties.
The page explains technical comparisons and calls the result a recommended representative,
without claiming artistic superiority. No embeddings or uniqueness signal is used.

## 13. Savings

Exact bytes sum removable alternatives while retaining one copy. Near bytes use distinct retained
SHA representatives so exact alternatives are not counted twice. Known hard links are excluded.
Exact and near values are separate; near savings require the user's redundancy judgment. Bursts
have no savings estimate. File bytes are not allocated disk blocks, compression or proven space.

## 14. Performance

Fresh-process measurements on Python 3.13.6/macOS ARM64, generated 256-pixel fixtures:

| Images | Candidate pairs | Expensive comparisons | Cold detection s | Cold total s | Warm total s | Peak MiB |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 60 | 60 | 0.081 | 0.592 | 0.047 | 80.64 |
| 500 | 302 | 300 | 0.392 | 2.860 | 0.207 | 95.73 |
| 1,000 | 604 | 600 | 0.815 | 5.433 | 0.374 | 103.14 |

Every warm pass reused detection and all photo caches; no candidate budget was hit. Peak RSS
covers the entire child process, imports, fixture generation and both passes. OS caches are warm;
these are single-run synthetic measurements, not high-resolution camera-roll guarantees.

## 15. UI

Duplicate Review adds relationship/group selection, separately labeled summary and savings,
paginated thumbnails, representative reasons and expandable pair/provenance evidence. Keep,
Favorite and Review Later persist locally. Member/group Not Duplicate corrections influence
reruns and survive clearing; source fingerprint changes expire their applicability. Stale source
or correction conflicts hide recommendations/savings. The restarted localhost UI was smoke-tested.

## 16. Validation

- All 65 tests passed in 6.15 seconds, including the previous 37 Phase 1 tests.
- Ruff lint passed; all 30 Python files passed formatting checks.
- Compileall passed; pip check found no broken requirements.
- Tests cover migration/data preservation, source/config invalidation, cancellation, hard links,
  corrupt thumbnails, correction persistence, CLI JSON and Streamlit interactions.
- Python socket-denial tests and child CLI execution passed, including the Phase 2 pipeline.
- Development threshold/verification/window experiments, final held-out JSON/CSV evaluation,
  false-positive diagnostics and final 100/500/1,000-image benchmarks completed.
- Browser smoke verified the completed fixture scan, group summaries, previews and review controls.
  Restarting Streamlit resolved stale imports retained from the Phase 1 process.
- No fresh dependency audit was needed for new packages: Phase 2 adds none. The historical Phase 1
  audit remains available. Socket tests are not packet capture or a complete dependency audit.

Artifacts: `benchmarks/phase2-evaluation.json`, `phase2-measurements.csv`,
`development-diagnostics.json`, `phase2-performance.json` and `phase2-review.jpg`.

## 17. Known limitations

Synthetic pair labels provide bounded evidence, not real-world photographic accuracy. Crops,
rotation, smooth scenes, timestamp gaps and greedy grouping reduce recall. Work caps can truncate
search; exact canonicalization can reduce burst coverage. Fingerprints depend on size/mtime unless
thorough analysis is requested. Only macOS was exercised; POSIX locking excludes Windows. HEIC/RAW,
high-resolution latency, authenticated hosting and static typing remain unsupported/unvalidated.
Sources are never modified; no deletion recommendation is automatically executed.

## 18. Phase 3 considerations

Before broad accuracy claims, collect consented private real-photo labels with independent capture
families and adversarial negatives. Keep frozen held-out sets and calibrate reliability only on
adequate separate data. Future embeddings need model/checkpoint/preprocessing/runtime provenance
and must remain distinct from exact/near/burst rules. No Phase 3 implementation was begun.
