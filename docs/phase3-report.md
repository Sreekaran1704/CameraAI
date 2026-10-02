# PhotoCull Phase 3 completion report

**Decision: retain hash-only as the default.** Local embeddings recover difficult synthetic
near pairs, but both hybrids produce dangerous new false positives on the expanded hard set.
Version 0.3.0 provides opt-in experimental models, local cache/provenance, bounded retrieval,
explainable rules and reproducible comparisons. No Phase 4 implementation was begun.

## 1. Embedding models evaluated

Final A/B candidates are MobileNetV3 Small ImageNet1K V1 and TinyCLIP ViT-8M/16 Text-3M YFCC15M.
MobileNet uses torchvision's pooled pre-classifier features. TinyCLIP uses its projected image
encoder through OpenCLIP. Both ran locally on CPU, without remote inference.

MobileCLIP-S1 was initially researched/downloaded, then excluded after reading its current
research-only license, which disallows product development. No MobileCLIP accuracy result informs
the final choice. TinyCLIP's model card identifies its license as MIT. Sources, preprocessing and
setup commands are in [embeddings.md](embeddings.md).

## 2. Sizes and dimensions

| Model | Weight bytes | Approx. MiB | Dimensions | Float32 vector payload/photo |
| --- | ---: | ---: | ---: | ---: |
| MobileNet | 10,306,551 | 9.83 | 576 | 2,304 bytes |
| TinyCLIP | 46,948,845 | 44.77 | 512 | 2,048 bytes |

Pinned full SHA-256 checkpoint hashes and versioned preprocessing are stored with the model
setup manifest and evaluation identity. MobileNet uses 256-short-edge/224-center/ImageNet
normalization; TinyCLIP uses 224-short-edge/224-center/CLIP normalization. Both honor EXIF
orientation and normalize output vectors to unit length.

## 3. Frozen hash-only baseline

The Phase 2 dataset content and label hashes exactly match the historical artifact. Thresholds,
split, scoring and duplicates_v1 remain unchanged. Held-out near pair results reproduce:
60 TP, 1 FP, 24 FN, 66 TN; precision 98.36%, recall 71.43%, F1 82.76%.

Each original split contains 206 images and 163 labeled pairs: 12 exact, 84 near, 24 burst,
31 similar-but-not-duplicate and 12 unrelated. Near scoring excludes exact labels. Unlabeled
pairs are not treated as negatives. No privately labeled real photos were supplied.

## 4. MobileNet hybrid

Original held-out classifier: 82 TP, 1 FP, 2 FN, 66 TN. Precision 98.80%, recall 97.62%,
F1 98.20%, false-positive rate 1.49%, false-negative rate 2.38%. It recovered 22 true positives
with no new false positives on the original labeled pairs. 129 predictions stayed unchanged.

Actual complete-link near groups retained only 60 labeled positives: precision 100%,
recall 71.43%, F1 83.33%. Pair-rule improvements therefore did not translate to better
grouped recall for this candidate.

## 5. TinyCLIP hybrid

Original held-out classifier: 84 TP, 1 FP, 0 FN, 66 TN. Precision 98.82%, recall 100%,
F1 99.41%, false-positive rate 1.49%, false-negative rate 0%. It recovered all 24 hash-only
false negatives with no new classifier false positives on that set. 127 predictions stayed
unchanged. The baseline's existing burst-frame false positive remains an error.

Actual near groups: 71 TP, 1 FP, 13 FN, 66 TN. Precision 98.61%, recall 84.52%, F1 91.03%.
This is the practical grouped result, rather than the classifier's 100% recall.

## 6. Selected strategy

Neither hybrid is accepted as the normal operating mode. TinyCLIP is the stronger experimental
candidate on these fixtures and had lower measured CPU cold latency, but expanded hard-negative
precision is insufficient. Both remain explicitly optional, with a warning. Disabled embeddings
select the frozen Phase 2 engine.

Candidate retrieval merges moderate pHash-radius candidates with bounded sorted-projection
embedding neighbors. No exhaustive NxN cosine matrix, training or hosted vector database exists.
Canonical SHA representatives prevent duplicate storage accounting; manual corrections and
complete-link membership constraints remain authoritative.

## 7. Threshold selection and protocol

Development-only search evaluated cosine 0.95/0.97/0.98/0.99/0.995/0.999, pixel verification
0.90/0.95/0.98 and moderate pHash 8/12/16: 54 operating points per model. Eligibility required
development precision at least 98%; choose highest recall, then precision, stricter cosine/pixel
guards and smaller pHash radius. Both selected cosine 0.95, pixel correlation 0.90 and pHash 8,
with corroborating dHash/aHash at most 16 and log-aspect difference at most 0.04.

Development metrics: MobileNet 83 TP/0 FP/1 FN, precision 100%, recall 98.81%; TinyCLIP
84 TP/0 FP/0 FN, precision/recall 100%. Confidence remains heuristic.

Development diagnostics showed that relaxed rules confused distinct timed burst frames.
The final recovery branch therefore requires equal comparable EXIF capture times when present;
unknown times can recover with the other guards. The frozen baseline branch is untouched.
Held-out labels did not select that rule or thresholds. Implementation fixes to checkpoint-key
mapping and canonical candidate filtering were verified before final results; they do not retune
the hash baseline. Reproduction runs retained the same selected operating points.

Retrieval uses eight fixed seeded projections and 16 neighbors. Those settings were fixed for
the comparison, not optimized against test labels. At least 97% original held-out precision
and a five-point recall improvement are required. Passing that initial test is insufficient
when supplemental hard examples expose precision below the same target.

## 8. Recovered false negatives

Original recoveries are mainly slight crops and rotations. Full example records retain IDs,
hashes, cosine, capture gaps/reliability, dimensions, ground truth and predicted relationship.
See [error records](../benchmarks/phase3-error-analysis.json) and
[original pair measurements](../benchmarks/phase3-measurements.csv).

The hard set adds eight positive transformations per base: stronger crop (6 pixels per edge,
versus Phase 2's 3), 3-degree rotation, slight perspective, color grading, contrast, brightness,
blur and partial obstruction. It adds a negative content-overlay/product proxy per base and
retains all original hard negatives and same-subject/different-date pairs.
Each split contains 314 images/271 labeled pairs, including 180 near labels. These are geometric
proxies, not real product or landscape photographs. The original negative categories include
sunsets/skies, same-layout documents/screenshots, walls, darkness and repeated patterns.

No thresholds were retuned on this supplemental set. Its held-out baseline recovered 108/180
near positives; MobileNet recovered 164/180 and TinyCLIP 170/180.

## 9. New false positives

Each hybrid adds six held-out hard-set false positives, all product/content-overlay negatives:
held_out-02, 04, 05, 07, 08 and 10 base versus base-product_negative. Together with the
baseline's existing error this yields seven false positives for each model.

Example: held_out-07-base versus its product_negative has MobileNet cosine 0.99756 and
TinyCLIP cosine 0.99784, despite the deliberately changed content. On held_out-10 TinyCLIP
cosine reaches 0.99916. Embedding agreement therefore cannot establish duplicate content.
Hash/pixel corroboration at the selected operating point still misses these differences.
The full report exposes hashes, dimensions and unknown capture-time provenance for each error.
Raising a threshold after inspecting these held-out examples would be test-set tuning; no such
retuning was done. They justify rejecting a default rollout.

## 10. Precision/recall/F1 comparison

| Original held-out pair rules | Precision | Recall | F1 | FPR | FNR |
| --- | ---: | ---: | ---: | ---: | ---: |
| Frozen hash | 98.36% | 71.43% | 82.76% | 1.49% | 28.57% |
| MobileNet hybrid | 98.80% | 97.62% | 98.20% | 1.49% | 2.38% |
| TinyCLIP hybrid | 98.82% | 100% | 99.41% | 1.49% | 0% |

| Expanded hard held-out pair rules | TP / FP / FN | Precision | Recall | F1 | FPR | FNR |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Frozen hash | 108 / 1 / 72 | 99.08% | 60% | 74.74% | 1.27% | 40% |
| MobileNet hybrid | 164 / 7 / 16 | 95.91% | 91.11% | 93.45% | 8.86% | 8.89% |
| TinyCLIP hybrid | 170 / 7 / 10 | 96.05% | 94.44% | 95.24% | 8.86% | 5.56% |

The hard set fails the precision-first principle despite higher F1. Original exact and burst
rules remain preserved; recovered near classification can also coexist with burst evidence.
Pair and grouped metrics have distinct meanings and exclude unlabelled pairs.

## 11. Inference and pipeline performance

Fresh child processes on Python 3.13.6/macOS ARM64, CPU/float32, batch 16, four torch threads.
Times are seconds. Inference excludes preprocessing/loading; cold full includes the entire scan.
Warm full includes cached vector and duplicate lookups. Grouping residual excludes the embedding
service's timed work but includes checksum/orchestration costs.

| Model | Images | Inference | Cold embedding service | Cold grouping residual | Cold full | Warm full | Peak MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MobileNet | 100 | 2.184 | 3.612 | 0.088 | 4.161 | 0.058 | 478.7 |
| MobileNet | 500 | 10.900 | 12.770 | 0.502 | 15.544 | 0.249 | 494.6 |
| MobileNet | 1,000 | 21.864 | 24.951 | 0.956 | 30.479 | 0.485 | 505.0 |
| TinyCLIP | 100 | 0.550 | 2.360 | 0.105 | 2.940 | 0.073 | 583.8 |
| TinyCLIP | 500 | 2.681 | 5.199 | 0.463 | 7.954 | 0.256 | 587.5 |
| TinyCLIP | 1,000 | 5.457 | 9.621 | 0.975 | 15.585 | 0.529 | 583.2 |

At 1,000, inference throughput was 45.7 images/s MobileNet and 183.3 TinyCLIP. Measured cold model
startup was 0.88/1.67 seconds, respectively; embedding service totals additionally include source
loading, deterministic preprocessing and vector publication. Warm duplicate duration was
0.205/0.201 seconds. All warm vectors and detection results hit caches; no work budget was hit.

Merged candidate counts for 100/500/1,000: MobileNet 901/4,799/9,787; TinyCLIP 912/4,780/9,771.
Each used 60/300/600 expensive pair verifications after guards. Bounded retrieval's cosine
ranking comparisons are separately recorded in [performance JSON](../benchmarks/phase3-performance.json),
and are additional to those pixel/hash verifications.

These are 256-pixel geometric fixtures, single-run measurements with warm OS caches. Peak RSS
covers imports, fixture generation, cold and warm passes. The Phase 2 0.81-second measurement
excluded embedding inference; it must not be compared directly with cold embedding totals.

## 12. Memory and storage overhead

At 1,000 images, vector NPY storage was 2,432,000 bytes MobileNet and 2,176,000 bytes TinyCLIP,
including headers. Other cache/database bytes are recorded separately. Model weights are shared
read-only through hard links in the benchmark and excluded from derived-cache size.
Peak process memory grew to approximately 505/583 MiB, versus the historical 103 MiB hash run.

Installed package directories measured torch 574,172,811 bytes, torchvision 8,887,084,
OpenCLIP 2,160,570 and timm 15,212,757. Those four total about 572.6 MiB; this is a measured
subset, not a complete fresh-environment installation size. Lockfile records actual versions.

## 13. Local deployment impact

Optional dependencies keep the core hash-only installation small. Inference can run entirely
on CPU; MPS is optional, not required. Model availability/checksum errors continue hash-only
analysis and display setup guidance. Ordinary scans never fetch weights. Cached vectors are
private derived data and stay in the marked local cache. Schema 3 stores metadata, not pixels.
No originals are modified, moved or deleted.

## 14. Free web-demo feasibility

Neither model was deployed or tested on a hosting plan. Compact weights are plausible for a
bounded demo, but PyTorch installation size, roughly 0.5–0.6 GiB measured process peaks and
additional Streamlit/concurrent-session memory make feasibility host-dependent. Cold import
and weight loading add latency. ARM64 timings do not predict a shared x86 host's CPU throughput.
No unconditional claim about any provider's current free tier is made.

An image-only ONNX export could reduce dependency cost for a future bounded demo; it was not
implemented. TinyCLIP's MIT model license is a better distribution fit than research-only
MobileCLIP. Regardless of hosting feasibility, these hybrid precision results do not justify
automatic duplicate recommendations in a public demo.

## 15. UI changes

The existing layout is preserved. Analysis Settings adds Disabled, MobileNet and TinyCLIP,
with normal thresholds hidden in configuration. Hash-only is the recommended default.
Experimental warnings explain the hard-set result. Evidence expands to model, cosine,
checkpoint identity and whether embeddings changed classification. Inference statistics expose
device, batch size, latency/throughput and cache hits. Settings apply to the next scan or
Recalculate groups; historical results retain their own provenance.

The localhost UI was restarted and smoke-tested: selecting TinyCLIP, recalculating the
412-image fixture scan, model/cache captions, groups and evidence. It was restored to hash-only
after the smoke test. Existing review decisions and corrections remain available.

## 16. Validation

- 83 portable tests pass, including all prior Phase 1/2 behavior and migration to schema 3.
- New coverage includes normalization, cosine, deterministic preprocessing, batching, cache
  corruption/hits, source/model/preprocessing/checksum invalidation, CPU fallback, missing model
  continuation, hybrid recovery, semantic negatives, capture-frame guards and exact accounting.
- The original content/label checksums and 60/1/24/66 baseline confusion counts match exactly.
- Lint, formatting, compilation and dependency consistency checks pass.
- Dependency/security audit found no known vulnerabilities at this run; advisory coverage is
  time-bounded, not a proof of future dependency safety.
- Tests deny Python network connections. Separate real MobileNet/TinyCLIP integration executed
  locally with sockets denied, verified dimensions/unit norms, deterministic repeated inference,
  and cached-vector equality. No tests download weights.
- A/B1/B2 development experiments, held-out comparison, expanded hard evaluation, separate error
  records and all six 100/500/1,000-image performance runs completed.
- Streamlit AppTest coverage and real localhost browser smoke passed.

Artifacts include phase3-evaluation.json, phase3-error-analysis.json, phase3-measurements.csv,
phase3-performance.json, phase3-offline-integration.json, phase3-installation-size.json,
phase3-dependency-audit.json and phase3-review.jpg in benchmarks/.
No staging, commits or pushes were performed.

## 17. Limitations

This synthetic experiment does not establish real-photo accuracy. The hard content-overlay
labels deliberately treat changed content as nonduplicate; real-world redundancy labels need
human capture/context judgment. Moderate/large crops can remain misses; low-texture scenes are
excluded and ANN retrieval is approximate. Complete-link grouping trades recall for safety.
Default hash-only inherits the documented Phase 2 false positive. Experimental hybrid scores
are not calibrated probabilities. MPS, high-resolution workloads, Windows and hosted resource
limits were not validated. Fast fingerprints retain the size/mtime limitation.

## 18. Recommendation for Phase 4

Do not promote embeddings to the default yet. Collect consented private real-photo labels,
including repeated products, same-subject changes, documents and burst poses, with independent
development/held-out capture families. Preserve this failing hard set and create a fresh holdout
before future threshold/rule improvements. Evaluate content-preserving registration or more
localized verification as a separate experiment, with error budgets and actual group metrics.
Event clustering and ranking should wait for explicit Phase 4 authorization and independently
validated objectives. No Phase 4 work was begun.
