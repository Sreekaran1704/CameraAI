# PhotoCull Phase 5 completion report

Phase 5 implements explainable rankings and non-repetitive shortlists, Best Photos, event
highlights, local labels, and CSV/JSON manifests. It does not implement personalization.
Hash-only duplicates and the two-hour time-only event default remain unchanged. No deployment,
staging, commit, push, deletion, or Phase 6 work was performed.

## 1. Ranking variants

A: Technical Quality v1, with deterministic technical tie-breaks.
B: context-specific technical quality, representation and guarded uniqueness, followed by
greedy similarity penalties and soft coverage bonuses. Both production variants use hard
known exact/near/burst group suppression. Duplicate context always uses technical quality only,
even when B is selected. Burst context adds representation but no uniqueness.
C is rejected by configuration and reserved for Phase 6; no learned preference model exists.

The ranking feature choice is independent of duplicate/event model settings. Default B uses
existing pHash descriptors, explicitly labelled a perceptual-hash surrogate. Optionally it
reads validated existing MobileNet/TinyCLIP vectors; it never computes or downloads embeddings.
Incomplete vector coverage makes the entire context fall back to hashes, avoiding mixed spaces.

## 2. Formulas

Q = technical_quality_v1 in [0,1].
R = (cosine(normalized descriptor, normalized context centroid)+1)/2, clipped to [0,1].
U = min(cap, max(0, 1 - maximum cosine to sampled relevant peers)), with self excluded.
Uniqueness is zero for Q <0.20 or R <0.35; a singleton has zero uniqueness.
Sample at most 33 evenly indexed peers with stable photo-ID ordering. This is an approximate
local redundancy proxy, not a semantic novelty or emotional-value model.

A and duplicate B: score = Q.
Burst B: score = 0.70 Q + 0.30 R.
Event B: score = 0.60 Q + 0.35 R + 0.05 U.
Event selection utility = score - 0.25 max(0, cosine to selected) + new-region bonus.
The first candidate has no similarity penalty. Known duplicate/burst peers are excluded once
a member is selected. Selection can return fewer than K; it does not refill with suppressed peers.
Tie-breaks: score, sharpness, exposure, resolution, lower clipping, stable source ID.

## 3. Selected weights

Event Q/R/U: 0.60/0.35/0.05. Uniqueness cap 0.10, so its maximum contribution is 0.005.
Diversity lambda 0.25, new-region coverage bonus 0.05, quality gate 0.20,
representation guard 0.35, neighbor limit 32. Burst Q/R: 0.70/0.30; uniqueness zero.
Duplicate Q/R/U: 1/0/0, preventing an oddly cropped/damaged candidate from benefiting merely
because it is different. Technical proxies can still prefer a crop; no damage classifier exists.

Development compared event weights (0.9,0.1,0), (0.75,0.20,0.05), (0.60,0.35,0.05),
(0.60,0.20,0.20); lambda 0/0.1/0.25/0.4; caps 0.10/0.25: 32 combinations.
A separate development-only burst sweep compared quality weights 0.70/0.85/1.00.
Configuration and defaults are in config.py and configs/default.toml; parameters are recorded
in each cached recommendation.

B remains a diversity-oriented product mode, not a demonstrated human-preference improvement.
Its held-out NDCG is slightly lower than A, so A remains available and no superiority claim
is made. Cached TinyCLIP diagnostic performance did not justify requiring embeddings.

## 4. Evaluation design

ranking_fixture_v2: **48 whole source-scene families, 368 labelled candidates**.
Development/test each have 24 families and 184 candidates: four duplicate contexts with three
candidates each, four burst contexts with three each, 16 event contexts with 10 each.
Independent seeds 51704 and 101704; no source scene crosses the split.
Authored relevance 0–3, preferred/favorite flags, acceptable alternatives, temporal region,
context and known redundancy groups are saved before scoring. The authoring rubric prefers
intact captures and scene coverage, with explicit low-light/intentional-blur exceptions.
A contact sheet was visually inspected: benchmarks/phase5-label-contact-sheet.png.

This is a manually authored synthetic transformation rubric, **not a human preference study**.
No private real-photo sample or human annotations were supplied, and no private photo library
was searched. Emotional value and visual interest cannot be validated by these abstract images.
Only local generated images were used. Labels and SHA-256:
[phase5-labels.json](../benchmarks/phase5-labels.json).
Images remain in ignored benchmark-output/phase5-ranking-v2.

Weights were selected from development macro NDCG, then favorite recall and coverage; lower
lambda breaks remaining ties. Final A/B use identical held-out families and the same hard
suppression groups. These supplied group labels measure ranking conditional on known groups,
not end-to-end duplicate recall. The fixed operating point is also checked diagnostically with
real cached TinyCLIP vectors without retuning on test. A preliminary v1 fixture was superseded
to ensure duplicate/burst contexts contain only related captures, not unrelated event scenes.

## 5. A vs B held-out metrics

Macro average of K=1 for duplicate/burst and K=3 for events:

| Variant | NDCG | Precision@K | Recall@K | Favorite recall | Pair accuracy | Redundancy | Region coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 0.6213 | 77.78% | 66.67% | 65.28% | 75.56% | 0.00% | 77.78% |
| B | 0.6198 | 77.78% | 66.67% | 65.28% | 76.13% | 0.00% | 77.78% |

A development NDCG 0.6198; B development 0.6213. Held-out A 0.6213; B 0.6198.
B did not win on this holdout. These small differences have no confidence interval or
real-world validation. Shared suppression gives both variants zero known-group contamination;
this is a guardrail result, not evidence of better detection.

## 6. NDCG@K

Duplicate NDCG@1: A/B both 0.8571. Burst NDCG@1: both 0.8571.
Event NDCG@3: A 0.5034, B 0.5012. Cached TinyCLIP B macro NDCG: 0.6213.
Gain uses 2^relevance-1 and log2(rank+1) discount; ideal uses all labelled candidates.
Missing shortlist positions contribute zero. Context metrics and full ranks are inspectable in
[phase5-evaluation.json](../benchmarks/phase5-evaluation.json).

For the pooled 184-candidate held-out library, Top 20 NDCG is 0.1327 for both A/B.
That poor result is reported explicitly: high-frequency unrelated noise can score technically
well and dominate a pooled shortlist. Event-level evaluation alone would hide that failure.

## 7. Favorite recall

Macro favorite recall: both 65.28%; events 60.42%, duplicate/burst 75%.
Pooled Top 20 favorite recall is 7.14% for both, partly reflecting the small selection budget
and the noisy-outlier failure. Favorites are benchmark targets only; ranking does not receive
favorite labels as a feature. Existing Keep/Favorite/Review labels stay in SQLite, and the
Favorites view shows every current marked candidate, including redundant favorites.

## 8. Pairwise accuracy

A 75.56%, B 76.13% on held-out contexts. Pairs with equal relevance are ignored.
Accuracy compares raw ranking order, independently of the subsequent shortlist order.
It is not a learned pairwise preference model. MRR, where a favourite appears in the selected
list, is A 0.5764 and B 0.5694; absent favourites contribute zero.

## 9. Top-K redundancy

Both variants have 0% known-group duplicate contamination in held-out context lists and
pooled Top 10/20. Contamination counts selections after the first from the same labelled
redundancy group, divided by actual selected count. Production excludes at most one per known
exact/near/burst group, including overlapping memberships. No “Not Duplicate” override is
silently ignored: suppressed/corrected/stale groups are excluded from ranking constraints.

The real cached 488-photo integration produced Top 20 lists with zero known-group contamination.
Unknown duplicates missed by the frozen detector can still appear. Greedy diversity reduces
similarity but is not a categorical duplicate detector or guarantee against unknown repetition.

## 10. Event coverage

For individual events, coverage is the fraction of labelled relevant temporal/scene regions
represented by a relevant selected photo. Macro region coverage is 77.78% for both variants;
event-only coverage is 66.67%. No region is forced to contribute a low-scoring photo.
Production per-event coverage uses four soft temporal bins; the library view uses event IDs.
Coverage bonuses require Q>=0.20 and do not override hard suppression.

Pooled Top 20 raw context coverage is A 66.67%, B 79.17%, **but that includes irrelevant
outliers**. Relevant context coverage is only 16.67% for both; therefore raw coverage is not
presented as representative-content success. Unassigned photos share a separate library region.
Mixed/absent timestamps and uneven capture intervals make temporal bins imperfect.

## 11. Strongest failures

- High-frequency unrelated noise can beat intact captures on technical sharpness/contrast.
  The capped uniqueness term is too small to cause that failure by itself; Q remains a
  misleading proxy. Both A/B pooled Top 20 precision is only 20% on this deliberately hard set.
- Low-light and intentional blur exceptions lose to technically stronger alternatives.
  The system cannot infer the photographer's intention or emotional preference.
- A central photo can be repetitive or visually uninteresting; R is one component, not taste.
  The “boring center” rubric is synthetic and does not validate human interest.
- Emotional expression/meaning is unmeasured; no face recognition or emotional classifier exists.
- Known duplicates do not contaminate the measured lists; unknown missed duplicates remain a risk.
- Event subsections can be underrepresented when a noise candidate consumes a limited slot.
  A soft bonus avoids rigidly forcing poor candidates but cannot guarantee scene coverage.

[phase5-error-analysis.json](../benchmarks/phase5-error-analysis.json) lists missed favorites,
noise selections, low-light/blur cases, missing coverage, and contamination checks. No test-set
weight retuning was used to hide these failures.

## 12. Explanations

Each candidate exposes Q, R, capped U, actual context weights, sharpness percentile,
exposure/resolution indicators, noise proxy, selection similarity/penalty, coverage region and
applied bonus. Weak points identify low technical scores, intentional-blur ambiguity, low-light
ambiguity and unusual content. The selection score and raw rank are persisted for inspection.
Language uses Recommended, technical indicators, representation and diversity. It never
asserts universal aesthetic superiority. A percentile is a within-context empirical indicator,
not a calibrated photographic quality probability.

## 13. Performance

CPU/macOS ARM64, Python 3.13.6. Ranking consumes existing metadata and normalized vectors,
not original pixels. These single-run measurements use 488 real cached synthetic-source
records cyclically repeated when needed to reach 500/1000/5000 metadata candidates.
The larger rows do **not** represent additional unique-image inference or accuracy.

| Features | Records | Ranking s | Shortlist s | Peak MiB | Comparisons |
| --- | ---: | ---: | ---: | ---: | ---: |
| hash | 30 | 0.0038 | 0.0005 | 76.8 | 1470 |
| cached_tinyclip | 30 | 0.0004 | 0.0004 | 76.8 | 1470 |
| hash | 100 | 0.0010 | 0.0017 | 77.3 | 5267 |
| cached_tinyclip | 100 | 0.0012 | 0.0015 | 77.4 | 5267 |
| hash | 500 | 0.0051 | 0.0090 | 79.4 | 26467 |
| cached_tinyclip | 500 | 0.0062 | 0.0072 | 81.2 | 26467 |
| hash | 1000 | 0.0100 | 0.0162 | 84.0 | 52967 |
| cached_tinyclip | 1000 | 0.0121 | 0.0146 | 87.0 | 52967 |
| hash | 5000 | 0.0534 | 0.0893 | 107.2 | 264967 |
| cached_tinyclip | 5000 | 0.0629 | 0.0879 | 118.4 | 264967 |

Real vector dimension 512; cached reuse 100%, no inference. Hash mode requires no model.
Peak memory is cumulative process high-water mark including metadata/cache loading, not
Streamlit or encoder startup. The separate A/B metadata benchmark uses 64D synthetic vectors:
[phase5-performance.json](../benchmarks/phase5-performance.json).
Full cached measurements: [phase5-cached-performance.json](../benchmarks/phase5-cached-performance.json).

Work is O(N*L*D + N*K*D) with peer limit L~33 and K<=100, plus sorting O(N log N).
No dense all-pairs matrix. The measured 5000-record B hash stage is about 0.14s total; cached
512D B about 0.15s. Source scanning, original decoding, quality computation, model inference,
Streamlit rendering, and exporting large manifests are excluded.

## 14. Web-demo feasibility

Ranking B for 30 metadata candidates is CPU-feasible: measured hash ranking+shortlist about
0.0043s; cached 512D about 0.0008s; roughly 77 MiB benchmark-process peak. It adds no dependencies
or inference to the existing pipeline. A future uploaded-photo demo must still pay image decode,
quality/hash extraction and thumbnail costs, with strict pixel limits and isolated per-session
storage. Optional model computation is a separate preparation expense from Phases 3/4; ranking
itself only reads existing vectors and otherwise falls back to hashes.

The [official Community Cloud resource documentation](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)
lists approximate CPU/memory ranges, not guaranteed allocations. The lightweight ranking stage
should fit typical free CPU hosting; this is an inference from local measurements, not a hosted
concurrency test. No upload/cloud implementation or deployment was performed. The current app
continues to read local folders on localhost.

## 15. UI changes

Best Photos: Best 10, Best 20, Best per Event, Best per Burst, duplicate representatives,
Favorites. A/B selector, cache-only feature selector, sorting by rank/event/date/technical quality,
paginated cards, thumbnail/name/event/rank/quality, collapsible explanations, full-width
Keep/Favorite/Review controls suitable for narrow iframe-like viewports. Explicit event pages
now include Recommended Highlights with 3/5/10 options where event size allows; very small
events show their available count. Suppression can reduce the displayed count.

Existing Import/Overview/Duplicate Review behavior was preserved. Event representatives remain
separate from recommended highlights. Browser visual proof: benchmarks/phase5-best-photos.jpg.

## 16. Export

Choose any subset of displayed recommendations and download CSV or JSON.
Each record has source path/name, original recommendation rank, current event name, Q and quality
metrics, explanations/weaknesses, current user label. UI sorting does not overwrite algorithm rank.
Only metadata is exported; no originals are copied, moved, modified, deleted or bundled.
Exports intentionally contain local paths; users decide where to share them.

CSV quotes nested JSON and guards leading spreadsheet formula markers =/+/-/@ with a literal
apostrophe. JSON preserves exact source names/paths. Empty manifests are valid. Favorite exports
can include all favourites because explicit user labels are not automatically suppressed.

## 17. Validation

120 tests pass, preserving Phase 1–4 and adding ranking/suppression/coverage/stability/export/
favorite/cache/version/feature-reuse/UI checks. Lint, format, compilation and pip check pass.
No new dependencies; audit checks 87 registry packages with zero known vulnerabilities, skipping
the editable application. Real MobileNet/TinyCLIP ranking caches were reused with outbound Python
sockets denied, no inference, and 100% cache coverage. SHA-256 confirms 488 generated original
PNG files unchanged. A/B dev/held-out evaluation, pooled Top-K contamination/coverage,
error analysis, 30/100/500/1000/5000 metadata performance, Streamlit AppTest and browser smoke
completed. Schema 5 migration, model/source/runtime/parameter cache identity and manual membership
invalidation are covered. Derived-cache clearing removes ranking_results but preserves labels
and manual event state.

[phase5-validation.json](../benchmarks/phase5-validation.json),
[phase5-offline-integration.json](../benchmarks/phase5-offline-integration.json),
[phase5-dependency-audit.json](../benchmarks/phase5-dependency-audit.json).

## 18. Limitations

Synthetic authored labels are not real human taste. No 20–30-group private real-photo benchmark
was available. No aesthetic, face, emotional or intention inference; no personalization/training.
Hash representation is a weak proxy for meaningful scene diversity, and even cached embeddings
do not establish preference. Nearest peers are bounded samples; missing vectors cause whole-context
fallback. Both frozen detection/event defaults retain their documented recall/boundary limitations.
The ranker can recommend noisy/boring/low-light-inappropriate choices; B did not outperform A
on this holdout. Manual labels use existing source IDs and are not a content-history audit system.

Single CPU run, generated low-resolution source imagery, cyclic scale metadata, no confidence
intervals or high-resolution/hosted-concurrency benchmarks. Cached recommendations can accumulate
until Clear Derived Cache. No undo/history, encryption or network authentication; POSIX/macOS
validation and trusted-local-user assumptions remain. Socket denial is not a packet capture.
No originals are exported; users receive manifests only.

## 19. Recommendation for Phase 6

Collect consented real-photo preferences before training anything. Include 20–30 independent
groups/events with labels recorded before algorithm output, contextual low-light/blur choices,
different emotional moments, boring-center/outlier examples, and a fresh grouped holdout.
Measure both event and pooled-library relevance, coverage and detector-conditioned contamination.
Use manual favourites as explicit labels only until personalization is separately authorized,
privacy-scoped and evaluated against A/B. Preserve this synthetic failure set and do not imply
that personalization automatically fixes technical-proxy errors. **Phase 6 was not begun.**
