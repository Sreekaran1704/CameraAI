# PhotoCull Phase 4 completion report

Phase 4 adds local event discovery, uncertainty, a timeline, and persistent manual corrections.
Hash-only duplicate detection remains the production default. No Phase 5 functionality, deletion,
remote inference, deployment, staging, commit, or push was performed.

## 1. Methods tested

Time-gap segmentation at 15, 30, 60, 120, and 240 minutes; two-stage sparse DBSCAN with
MobileNetV3 Small and TinyCLIP ViT-8M/16; bounded HDBSCAN with both models; and purely visual
DBSCAN controls. No K-Means. HDBSCAN uses scikit-learn's implementation rather than another
compiled clustering dependency. The optional event extra installed scikit-learn 1.9.1,
SciPy 1.18.1, joblib 1.6.0, cloudpickle 3.1.2, and threadpoolctl 3.7.0.

DBSCAN evaluates a weighted sum of time separation/coarse-window scale and cosine distance,
with normalized vectors. HDBSCAN evaluates Euclidean concatenated features with square-root
weights; these are distinct distances, not numerically interchangeable epsilon settings.
The [official DBSCAN documentation](https://scikit-learn.org/stable/modules/generated/sklearn.cluster.DBSCAN.html)
supports sparse precomputed neighborhoods; [HDBSCAN](https://scikit-learn.org/stable/modules/generated/sklearn.cluster.HDBSCAN.html)
supports variable-density clustering. Neither algorithm guarantees real-world event semantics.

Development HDBSCAN ARI was 0.773 (MobileNet) and 0.837 (TinyCLIP), below corresponding selected
DBSCAN runs. Purely visual control ARI was 0.038 and 0.000 respectively: visually repeated
synthetic content merged across dates. Temporal windows materially prevent that failure.

## 2. Dataset composition

Deterministic event_fixture_v2: **488 PNG photos, 40 capture families, 80 true events, eight noise
photos**. Development and test each have 244 photos, 20 whole families, 40 true events, four noise.
Seeds 41704 and 91704 differ; all images in a capture family stay in one split. Family-specific
image seeds/compositions prevent identical camera images crossing development/test.
Two families per category per split: ordinary occasions, nearby different occasions, long gaps,
travel with changing visual content, same scene on different days, weak timestamps, absent
timestamps, screenshots, visual outliers, and mixed camera timestamp tiers.

Labels include photo ID, true event/null noise, timestamp, provenance, split, and family.
[phase4-labels.json](../benchmarks/phase4-labels.json) includes image SHA-256 for inspectability.
The generator and tuning grid are in event_evaluation.py; images remain in ignored local
benchmark-output/phase4-events-v2. This is synthetic ground truth; no private real-photo labels
were used. It does not substantiate real-world accuracy or deletion recommendations.

Missing-time fixture labels intentionally have no usable capture or filesystem timestamp.
The filesystem pipeline always has a file mtime and therefore groups those copied PNGs with
LOW_CONFIDENCE rather than treating curated benchmark timestamp absence identically.
The pipeline demo scans both splits together; its event count is not a held-out accuracy score.

## 3. Time-only results

The selected development gap is **120 minutes**. Gaps 15/30/60 gave development ARI 0.8572;
120/240 tied at 0.8743, with the shorter tied threshold selected. Test ARI 0.8743,
NMI 0.9671, pairwise precision 86.41%, recall 89.00%. Preserves variable scenery and longer
occasions, but merges close separate occasions. Time-only allows singleton events.

## 4. MobileNet results

Development-selected DBSCAN: time weight 0.1, visual weight 0.9, epsilon 0.15, minimum samples 2.
Held-out ARI 0.9054, NMI 0.9708, pairwise precision 100.00%, recall 83.00%.
It separated close occasions and rejected all four noise photos, but split visually changing
travel sequences. Embeddings use the existing pinned local MobileNet checkpoint/preprocessing.

## 5. TinyCLIP results

Development-selected DBSCAN: time weight 0.3, visual weight 0.7, epsilon 0.15, minimum samples 2.
Held-out ARI 0.9111, NMI 0.9749, pairwise precision 93.68%, recall 89.00%.
It retained travel sequences better than MobileNet, but merged one of two close-occasion
families on the held-out split. No assumption that the smaller or newer model wins.
Actual local model vectors were used, not hand-authored synthetic vectors for accuracy.

## 6. Selected default

**Time-only, 120-minute gap.** TinyCLIP's development ARI gain was 0.0490 and held-out gain 0.0368;
MobileNet lost six recall points. Those modest synthetic improvements do not justify model
startup, inference, hundreds of MiB of memory, and deployment dependencies by default.
The default decision considers a 0.05 ARI gain and at most 0.05 recall loss as material quality
gates plus CPU/memory cost; these product tradeoffs were considered after the first exploratory
run, not claimed as a preregistered research acceptance test. Operating points themselves are
chosen from development only. Held-out labels were not used to retune distances.

Both visual methods are available as explicit experimental event choices. Duplicate settings
remain independent and disabled for embeddings by default. No Phase 3 hybrid duplicate rules
are used for event membership.

## 7. Parameters and timestamp reliability

Default: gap 120 minutes, maximum continuous span 18 hours, separate timezone-aware EXIF,
naive EXIF, and filesystem partitions, no GPS requirement. Visual alternatives use coarse
240-minute gap windows, the same 18-hour span ceiling, 64 following time-ordered candidates,
and minimum density two. HDBSCAN windows cap at 256 records; oversized windows remain
unassigned with an explicit warning. Time and visual weights/epsilon are configurable;
development tested weights 0.1/0.3/0.6 and epsilon 0.15/0.25/0.40.

Aware EXIF converts to UTC for comparison, including differing offsets. Naive EXIF stays
wall-clock time without assuming the host timezone. Filesystem awareness is partitioned too.
Confidence: aware EXIF high, naive EXIF medium, filesystem low, absent none. Long events can
bridge a time-only threshold when visual support passes the two-stage density distance.
The 18-hour ceiling deliberately limits chain growth; multi-day occasions can split.

## 8. Held-out metrics

| Method/model | ARI | NMI | Pair precision | Pair recall | Purity | Predicted events | Unassigned |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| disabled | 0.8743 | 0.9671 | 86.41% | 89.00% | 94.26% | 42 | 4.92% |
| mobilenet | 0.9054 | 0.9708 | 100.00% | 83.00% | 100.00% | 46 | 6.56% |
| tinyclip | 0.9111 | 0.9749 | 93.68% | 89.00% | 97.54% | 41 | 6.56% |

Truth has 40 events per split. Truth noise and predicted unassigned receive individual singleton
labels for ARI/NMI. Pairwise positives require two photos of the same non-noise true event;
predicted positives require a shared actual event. Purity includes singleton noise/unassigned
labels and can be inflated by oversplitting; assess it alongside recall/unassigned rate.
No silhouette score is used as a selection criterion. Exact counts and category breakdowns:
[phase4-event-evaluation.json](../benchmarks/phase4-event-evaluation.json).

## 9. Over-merging

Time-only: 84 false-positive pairs — 72 across the two close-occasion families, 12 attaching
visual outliers to occasions. MobileNet: zero on this synthetic holdout. TinyCLIP: 36, from
one close-occasion family. Same-scene/different-day families have zero false-positive pairs
under every two-stage finalist. Purely visual controls demonstrate severe cross-date merging.

## 10. Over-splitting

Time-only: 66 false-negative pairs — 30 from missing timestamps, 36 from mixed camera tiers.
MobileNet: 102, adding 36 travel pairs where scenery changes. TinyCLIP: 66.
Selected 120-minute time segmentation and both visual finalists preserve long-gap families.
The narrower time thresholds split 95-minute gaps. Mixing camera clocks without evidence
is deliberately avoided; users may manually merge them.

## 11. Outliers and uncertainty

Statuses: EVENT_MEMBER, UNASSIGNED, LOW_CONFIDENCE, each with a persisted reason and timestamp
tier/confidence. Absent usable timestamps stay unassigned. Visual isolated/missing-vector
records stay unassigned. Time-only does not detect visual outliers: it groups the two visual
noise photos and makes singleton events for the two filesystem screenshots, marking those
filesystem assignments low confidence. Visual finalists leave all four true noise records
unassigned. Screenshots are benchmark labels only; no OCR or screenshot classifier was added.

Naive EXIF and filesystem event assignments are LOW_CONFIDENCE. Bounded DBSCAN search marks
dense affected windows low confidence when the neighborhood limit truncates potential search.
Missing optional packages/weights fall back to time-only with a visible provenance warning.

## 12. Manual corrections

SQLite schema 4 stores immutable automatic event_runs and scan links separately from manual_events
and fingerprint-scoped event_overrides. Rename, move, remove, merge, and subset split commit
atomically. Editing materializes the affected event's current members into persistent manual
state, preserving names and membership through new thresholds, versions, scans, app restarts,
and derived-cache clearing. New automatic photos do not silently extend a frozen manual event.

A changed source fingerprint retains the old correction and explicitly marks its new assignment
LOW_CONFIDENCE for review. Old UI edits validate every affected source against its live file
before writing. Sources missing from a run do not display stale memberships. There is no
undo/history interface yet; users can correct membership again. These edits change metadata,
never image files.

## 13. Representatives

Choose up to three photos. Visual runs approximate an embedding medoid by selecting near the
normalized cluster centroid; time-only uses the temporal median as a temporal-medoid target.
TechnicalQualityv1 breaks centrality ties, with stable IDs resolving remaining ties. Identical
SHA-256 and pHash distance <=2 suppress repeated representatives. This is lightweight event
coverage, not Best Photos ranking. Unchanged visual automatic representatives persist in UI
reads; manually changed membership can use the temporal-center fallback when vectors are not
loaded. Very uniform events can have just one representative.

## 14. Runtime and memory

Fresh CPU processes on macOS ARM64, Python 3.13.6, 256px generated photos, one measurement per
condition, warm OS filesystem caches. Cold event time includes model loading/inference and
clustering, but excludes photo generation and original scanning/quality/duplicate analysis.
Cold clustering includes the first sklearn import. Warm time reuses 100% of embedding NPY cache
records. Time-only uses no embeddings (cache-hit rate not applicable).

| Model | Images | Cold event s | Cold cluster s | Warm event s | Peak MiB | Candidates | Events |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| disabled | 30 | 0.004 | 0.004 | 0.000 | 77.6 | 0 | 2 |
| disabled | 100 | 0.003 | 0.003 | 0.001 | 77.9 | 0 | 5 |
| disabled | 500 | 0.006 | 0.006 | 0.003 | 79.1 | 0 | 25 |
| disabled | 1000 | 0.010 | 0.010 | 0.006 | 80.7 | 0 | 50 |
| mobilenet | 30 | 3.042 | 1.383 | 0.007 | 619.7 | 235 | 2 |
| mobilenet | 100 | 4.269 | 1.154 | 0.014 | 560.4 | 950 | 5 |
| mobilenet | 500 | 13.745 | 1.393 | 0.069 | 540.7 | 4750 | 25 |
| mobilenet | 1000 | 25.302 | 1.456 | 0.138 | 590.4 | 9500 | 50 |
| tinyclip | 30 | 2.988 | 1.214 | 0.004 | 722.0 | 235 | 2 |
| tinyclip | 100 | 3.165 | 1.195 | 0.015 | 667.4 | 950 | 5 |
| tinyclip | 500 | 6.053 | 1.294 | 0.065 | 658.9 | 4750 | 25 |
| tinyclip | 1000 | 9.711 | 1.460 | 0.141 | 681.8 | 9500 | 50 |

[phase4-image-performance.json](../benchmarks/phase4-image-performance.json) includes startup,
inference and cache stats. Real dimensions: MobileNet 576, TinyCLIP 512. Memory is process high
water mark including imports and fixture generation, not incremental vector storage.

5,000 metadata records: time 0.029s, DBSCAN 0.232s, HDBSCAN 0.161s, 250 events; visual methods
47,500 comparisons and about 237 MiB cumulative peak. This separate scale probe uses preloaded
64D synthetic metadata vectors and excludes inference; it is not a 5,000-photo accuracy/model
speed claim. Memory is cumulative across methods in that metadata process; fresh per-model image
measurements above provide cleaner comparison. HDBSCAN comparison count is a within-window
pair upper bound, not instrumentation of its internal tree distances.

Sparse DBSCAN costs bounded O(N*K*D) comparisons with K=64 and linear sparse graph storage.
Time-only sorting costs O(N log N); representative sorting is bounded by each cluster's size.
HDBSCAN is restricted to small windows to bound potentially dense work. Candidate truncation
may reduce recall; no global dense N×N matrix is allocated by the DBSCAN path.
[phase4-metadata-performance.json](../benchmarks/phase4-metadata-performance.json).

## 15. Web-demo feasibility

**Time-only is feasible for 30 photos on CPU**: the measured event stage is about 0.004s and
78 MiB in its fresh benchmark process. This excludes megapixel decoding and Streamlit's own
process; use conservative image limits and serialized jobs. Thirty-photo cold visual stages
were around 3 seconds locally and 620/722 MiB (MobileNet/TinyCLIP). Free-hosted CPU throughput
can differ substantially, and multi-session/decoded-image overhead makes the visual options
a weaker default.

The [official Community Cloud resource page](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)
currently lists approximate ranges of 0.078–2 CPU cores and 690 MB–2.7 GB memory, labelled as
February 2024 figures and subject to change. These are not an allocation guarantee.
Feasibility is an inference from local measurements, not a hosted load test. A future upload
demo would need per-session storage isolation, bounded input pixels, cleanup, and an explicit
privacy disclosure that uploaded files reach the hosting machine. None was implemented or
deployed; the current app remains localhost and reads local folders.

## 16. UI

Events navigation, three summary counts, paginated neutral-name cards, date/time ranges and
representative thumbnails, member browsing, rename/merge/move/remove/split forms, and
unassigned/low-confidence review. A clean paginated bar/point timeline uses timezone-aware
EXIF in UTC; naive/filesystem/mixed manual events remain separate provenance rows rather than
sharing that axis. Experimental event model choice is separate from duplicate embedding choice.
Only locally derived thumbnails are displayed. Screenshot: benchmarks/phase4-events.jpg.

## 17. Validation

110 tests pass, preserving all prior-phase tests and adding event/correction/UI contracts.
Ruff lint and formatting pass, compilation and pip check pass. Dependency audit: 87 registry
packages checked, zero known vulnerabilities; editable PhotoCull intentionally skipped.
Real MobileNet and TinyCLIP execution with outbound Python sockets blocked succeeds, with
100% warm embedding reuse and automatic snapshot reuse. SHA-256 confirms all 488 generated
original PNGs unchanged. The existing frozen duplicate accuracy test remains unchanged:
hash-only production behavior and Phase 3 experimental status are preserved.

A/B/C comparison, error reports, 30/100/500/1000 image and 5000 metadata benchmarks, pipeline
smoke, Streamlit AppTest and browser visual smoke completed. Full details:
[phase4-validation.json](../benchmarks/phase4-validation.json),
[phase4-offline-integration.json](../benchmarks/phase4-offline-integration.json),
[phase4-dependency-audit.json](../benchmarks/phase4-dependency-audit.json).

## 18. Limitations

Synthetic labels repeat a small set of visual/time patterns; no real-camera-roll generalization
claim or confidence calibration. No confidence intervals or repeated timing distributions.
Family grouping prevents identity leakage but common generator recipes remain shared.
Timestamp gaps cannot reliably separate close occasions, filesystem times may reflect copies,
and naive camera clocks cannot be aligned automatically. No GPS, semantics, faces or OCR.
Visual clustering can oversplit travel and coarsely distinct moments or merge similar occasions.
Neighbor caps/18-hour span caps and HDBSCAN window limits trade recall for bounded work.
Single-photo events and all-noise libraries need human review; no model-based event naming.
POSIX-only locking and local single-user trust assumptions remain. Model/cached vectors need
local storage protection; clear-cache is not forensic erasure. No undo/audit UI for manual edits.
High-resolution, Linux/Windows, MPS, hosted concurrency and adversarial filesystem behavior were
not validated. Socket denial is not an OS firewall or packet capture.

## 19. Recommendation for Phase 5

Before adding ranking, collect consented locally labelled real event families and a fresh
grouped holdout. Validate event boundaries, uncertain assignments and representative usefulness
with user corrections. Keep Phase 4's default and frozen duplicate settings until stronger
evidence supports a change. Any Best Photos criteria should distinguish technical indicators
from personal/artistic preferences and remain inspectable. **Phase 5 was not begun.**
