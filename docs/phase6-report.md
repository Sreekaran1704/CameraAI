# PhotoCull Phase 6 completion report

PhotoCull 0.6.0 implements optional local explicit preference learning. **The central human
hypothesis remains unanswered:** zero real human preference labels have been supplied. The
user will label afterward. The model mechanics and controlled simulations are validated;
no claim that C improves this user's taste is justified. Phase 7 was not begun, no deployment
was performed, and no Git staging/commit/push occurred.

## 1. Preference model implemented

personalized_ranking_v1 uses L2-regularized, no-intercept pairwise logistic regression,
implemented with the existing NumPy dependency. A decisive comparison supplies
d = (features(A) − features(B)) / training-photo standard deviation. P(A preferred over B)
is sigmoid(w·d). Reversing sides yields the complementary probability. Ties, skips and
deliberate repeats are stored separately and excluded from binary fitting.

Fit uses at most 60 Newton iterations. L2 is selected from 0.1/1/10 on inner
development groups; no full neural model, remote training, face/identity features or
fine-tuning. Model files are JSON in SQLite, never executable pickle.

Ranking C is separate from frozen A/B:
C = alpha × generic B relevance + (1−alpha) × sigmoid(w·(x−training mean)/scale).
Alpha is selected from 0/.25/.5/.75/1 on inner development groups. After scoring, the existing
B MMR coverage/diversity and known duplicate/burst suppression policy is applied.
The 100-example primary simulation selected alpha=0, L2=10;
this does not prescribe the same hyperparameters for human feedback. Activation and model
hyperparameters are recomputed after valid feedback corrections.

## 2. Features used

Fifteen interpretable scalars: sharpness, exposure, contrast, resolution, clipping,
entropy/8, noise residual MAD/255, colorfulness/255, technical_quality_v1, landscape flag,
log aspect ratio, event representativeness, guarded uniqueness, redundancy (1−uniqueness),
and brightness. The version is preference_features_v1.

Training mean/scale are fitted on unique training photos only; constant columns use scale 1.
Pair differences cancel the mean; per-photo preference scores center on the training mean.
Representative/uniqueness signals use the fixed hash-based contextual features, independent
of downloaded model availability. No full embedding vector/PCA/preferred-photo embedding
experiment is included. The model dimension is exactly 15. Correlated quality and
redundancy signals are explicitly documented.

## 3. Minimum comparison threshold

**50 decisive training comparisons** is a conservative provisional floor. Activation also
requires at least three independent training components, at least ten decisive held-out
pairs across two components, and C held-out accuracy strictly above both A and B. Thus 50
total clicks need not activate C. Ties/skips/repeats do not count.

This guard prevents premature ranking claims; nominal improvement on two groups can still
be noisy. Activation is labeled experimental and does not assert statistical significance.
If counts/evidence are insufficient or C does not improve, Best Photos falls back to frozen B
and says “Personalization is not active yet.” Generic A/B remain available.

## 4. Train/test grouping strategy

Events AND known exact/near/burst components are unioned transitively. No individual-photo
random split. Sticky pre-label SHA-256 group allocation reserves about 20% of independent
components as holdout (seed 170406). A per-source fingerprint ledger persists both partition
and historical component identity. Manual splitting preserves historical connectivity,
including inner development grouping; merging train/holdout components quarantines the
entire combined component as holdout.

Current records reconcile this ledger before training. Changed source fingerprints, analysis
versions, feature values or feature provenance invalidate stale examples. Train and holdout
group overlap OR photo/fingerprint overlap is rejected, even with inconsistent group names.
The inner development split uses training groups only to select alpha/L2; the outer holdout
does not tune parameters. UI scores/recommendations are hidden before pair labeling.

Synthetic experiments use the entire preexisting 24 development families as training pool
and 24 test families as holdout, preserving all within-family near-duplicate/burst members.
No image from a family crosses the outer split.

## 5. A/B/C ranking results

The **Phase 5 baseline stays frozen**: authored synthetic shortlist NDCG A=0.621, B=0.620.
B did not outperform A. Existing ranking_v1.2, quality_v1 and selected generic parameters
were not retuned. Both retained zero known-group contamination.

The following is a **different controlled, simulated taste experiment** on 368 generated
images, not a human study. Its taste rule favors exposure/color/brightness and avoids noise/
the authored unrelated outlier. Pair labels and graded labels come from that predefined
oracle; they are not empirical human judgments. Do not compare these NDCGs directly to Phase 5.

Primary random-seed 170406, 100 training pairs, 744 held-out decisive pair labels in 24 groups:

| Ranking | Pair accuracy | Raw NDCG@3 | Raw favorite recall@3 | Kendall tau-a |
|---|---:|---:|---:|---:|
| A | 0.672 | 0.683 | 0.833 | 0.246 |
| B | 0.675 | 0.683 | 0.833 | 0.243 |
| C | 0.890 | 0.913 | 0.792 | 0.419 |

These graded metrics rank ALL photos within each held-out group by raw A/B/C scores, before
MMR/suppression. They assess preference scoring, not final shortlist coverage. Runtime C
shortlist suppression was separately tested and offline-smoked with zero known-group
contamination. Pairwise training labels alone do not justify NDCG/favorite labels.

## 6. Pairwise accuracy and paired hypothesis comparison

- A: 0.672, group bootstrap 95% interval [0.646, 0.696].
- B: 0.675, group bootstrap 95% interval [0.645, 0.706].
- C: 0.890, group bootstrap 95% interval [0.846, 0.933].

Intervals use 300 bootstrap samples of independent groups, preserving within-group clustering.
C vs A: 16 group wins, 0 losses, 8 ties. C vs B: 16 wins, 0 losses, 8 ties. Exact two-sided
group sign-test p=0.0000305 in this simulation (16 non-tied independent family comparisons).
The test is descriptive evidence for a feature-dependent simulator, **not evidence about
this user or real human taste**. Small human studies may not support significance; the tool
withholds the sign-test p-value below six non-tied group comparisons.

The continuously reused app validation set is not an untouched final study. The human
protocol recommends an additional blind final set of entirely new events after development.

## 7. NDCG

Simulated raw NDCG@3 A/B=0.683; C=0.913.
The private evaluator supports independent human relevance grades 0–3. It excludes partially
graded groups and validates label types/ranges. Without complete independent grades it reports
NDCG as unavailable; binary preferences are not converted into invented full rankings.

## 8. Favorite recall

Primary simulation favorite recall@3 fell from 0.833 in A/B
to 0.792 in C despite pairwise/NDCG gains. This is a real
tradeoff in this controlled evaluation, and a reason not to assume C universally wins.
Human favorite recall needs explicit independently marked held-out favorites. Ordinary
Favorites remain separate and are never silently treated as pairwise preference training labels.

## 9. Learning curve

At each budget, inner-group development selects alpha/L2 and the fixed outer test groups
are evaluated. The first ten examples seed random/uncertainty sampling identically.
The table averages three sampling seeds (170406/170407/170408); it is not a human learning curve.

| Training pairs | Random accuracy | Random NDCG@3 | Random favorite recall | Uncertainty accuracy | Uncertainty NDCG@3 | Uncertainty favorite recall |
|---|---:|---:|---:|---:|---:|---:|
| 10 | 0.675 | 0.683 | 0.833 | 0.675 | 0.683 | 0.833 |
| 20 | 0.727 | 0.758 | 0.833 | 0.759 | 0.829 | 0.931 |
| 30 | 0.772 | 0.812 | 0.889 | 0.733 | 0.791 | 0.917 |
| 50 | 0.789 | 0.895 | 0.931 | 0.829 | 0.860 | 0.944 |
| 75 | 0.878 | 0.924 | 0.847 | 0.920 | 0.980 | 0.972 |
| 100 | 0.879 | 0.924 | 0.847 | 0.907 | 0.990 | 0.972 |

[Learning curve SVG](../benchmarks/phase6-learning-curve.svg),
[standard Altair/Vega-Lite specification](../benchmarks/phase6-learning-curve.vl.json),
[machine-readable summary](../benchmarks/phase6-learning-curve-summary.json).
Chart bars show the three-seed range, **not confidence intervals**.

At 10 labels development often chooses alpha=1, so nominal C equals generic B. Outcomes at
20/30 vary substantially; 50 is a plausible initial floor for this simulator, not a measured
human requirement. Human usefulness and the correct floor remain to be established with the
private benchmark. The UI can compute an actual local pairwise learning curve; raw grading
metrics require the separate private grading file.

## 10. Consistency analysis

Original and deliberate repeat labels are compared by canonical winner, independent of displayed
side. Ties compare as ties; skips are omitted; repeats never inflate training or validation
accuracy. Displayed sides alternate. Review/correction and undo are supported with revisions.
No human repeats exist, so real agreement is **unavailable**, not assumed 100%.
Unit tests verify repeat agreement and correction behavior; the tool never penalizes inconsistency.

## 11. Active-learning result

The offline experiment compares random sampling to closest-to-50/50 model uncertainty,
drawing labels only from the training pool. Across three seeds uncertainty has stronger
mean 75/100-example accuracy but mixed earlier results; one run stayed at baseline through 50.
No reliable claim that it needs fewer human labels is supported. The app offers contextual
random/useful/uncertainty modes; uncertainty adds a prediction bonus while retaining useful
context priority, and only uses an existing fitted model. Before fitting, contextual useful
pairs remain the cold-start strategy. Pairs are bounded score neighbors plus all combinations
only for contexts of at most 12 photos. Unrelated singleton photos are not compared.
Exact prior pairs are excluded unless consistency repetition is explicitly enabled.

## 12. Sharp-noise experiment

A separate technical_quality_noise_guard_experiment_v1 tested:
Qv1 − penalty × min(1, noise_residual_mad/25).
Penalty .5 was selected on 16 development scene-versus-random-noise pairs; 16 independent
held-out synthetic pairs improved from 0/16 to 16/16 preferring the authored detailed scene.
This is a narrow synthetic result; genuine detailed texture, low light, compression and
intentional grain need human/real-photo validation. **Not adopted** into generic or personalized
runtime scores. The frozen technical_quality_v1 was unchanged. C can learn noise-related
associations only when explicit choices support them; no global sharpness reduction occurred.

## 13. Learned preference interpretation

The UI displays substantial standardized coefficients only when |coefficient|≥.15 and sign
agreement≥90% in 30 grouped training bootstrap fits. It reports “log-odds per training-photo
standard deviation,” not fabricated aesthetic rules. These are descriptive sign-stability
screens, not corrected significance tests or causal explanations.

Individual recommendations show the three largest absolute centered/scaled linear feature
contributions and the generic prior weight. They correctly reflect w·((x−mean)/scale); the
sigmoid/blend are nonlinear, so contributions are not falsely presented as additive final
score changes. Correlated features can redistribute coefficients. No meaningful real-user
tendency exists yet. Logistic likelihoods and preference scores are explicitly uncalibrated;
calibration has not been evaluated.

## 14. Performance

Measured locally on Apple Silicon/macOS/Python 3.13; metadata only:

- Bare 100-example fit: 0.15 ms.
- Scoring 368 feature records: 1.49 ms.
- Full 144-training-example tuning + validation + 30 grouped bootstrap fits:
  168.0 ms.
- Full fit and persistence with 192 isolated feedback records:
  143.9 ms.
- Model lookup/reload: 6.7 ms.
- Persisted full model JSON: 5,361 bytes.
- Isolated schema + 192 feedback records: 624 KiB;
  incremental learning data above empty schema: 400 KiB.

Near-instant retraining is met at current scale. This excludes thumbnail decoding, source scan,
Streamlit startup and public hosting capacity. Store snapshots repeat feature metadata per
comparison; large histories may require optimization later.

## 15. Web-demo behavior

Local Edition persists feedback, revisions, partitions and model in private SQLite schema 6.
Web Demo keeps all learning state in independent Streamlit session memory. The non-widget mode
flag survives navigation to Best Photos. PHOTOCULL_WEB_DEMO=1 forces this behavior and prevents
turning persistent preferences on. Session state can live in server RAM until the session
expires; it is not permanent retention or cryptographic isolation. This design is implemented
and tested; no public deployment was performed. No privacy claims about a hypothetical host.

## 16. UI changes

Dedicated Preferences page has Teach PhotoCull, contextual A/B/Tie/Skip, deliberate consistency
repeat, Undo latest choice/correction, Review previous choices/Save correction, Learning Progress,
local learning-curve computation, Learned Preferences and confirmed Reset. Training/held-out
sets are explicit and scores remain hidden before labeling. Stale comparisons hide current
thumbnails to prevent relabeling changed content accidentally.

Best Photos adds Generic/Personalized mode. Generic A/B controls remain available; in C mode
they are disabled and the fixed B prior is stated. Insufficient evidence produces an honest
fallback. All existing views, explanations, label controls and metadata exports remain.
[Comparison screenshot](../benchmarks/phase6-preferences.jpg),
[cold-start screenshot](../benchmarks/phase6-cold-start.jpg).

## 17. Validation results

**142 tests pass**, including all 120 Phase 1–5 tests and 22 Phase 6 cases: connected grouping,
historical grouping, overlap rejection, pair generation, feature dimensions/differences,
logistic symmetry/training, ties/skips/repeats, corrections/undo, threshold/activation/failure,
persistence, reset, stale invalidation, generic fallback, C/suppression, learning curves,
incomplete grade handling and local/forced-session UI tests. Outbound Python sockets are denied
throughout tests and offline evaluation/integration.

Lint, formatting (76 Python files), compilation and pip dependency checks pass. Audit checks
87 registry dependencies with zero known vulnerabilities, skipping the editable PhotoCull project.
No new runtime dependencies. SHA-256 verified 488 generated originals unchanged. Browser smoke
shows the comparison workflow and inactive 0/50 progress; no artificial human labels were written.

[Validation record](../benchmarks/phase6-validation.json),
[offline integration](../benchmarks/phase6-offline-integration.json),
[audit](../benchmarks/phase6-dependency-audit.json),
[simulated evaluation](../benchmarks/phase6-simulated-evaluation.json),
[local empty-label evaluation](../benchmarks/phase6-local-evaluation.json),
[label provenance](../benchmarks/phase6-simulated-label-provenance.json).

## 18. Limitations

Real-user A/B/C accuracy, NDCG, favorite recall, calibration and consistency are unavailable
until labeling. Simulator labels derive from a feature-dependent oracle favorable to a linear
learner; they cannot validate real aesthetics/emotion/intent. Strong grouped synthetic scores
and a small p-value do not change that limitation. Primary C favorite recall declined.
The activation floor is provisional and repeatedly reused validation can be optimistic.

Conservative connected components can reduce eligible independent groups substantially. Known
duplicate detection limitations remain; unknown related photos can still escape grouping.
Scalar features miss meaning, people, emotion and intentional blur. No full embedding/PCA,
neural training or global noise-score replacement. At-rest data is not encrypted; reset is
logical deletion plus SQLite reclamation, not forensic erasure from backups/SSD.
Windows/local-host authentication limitations remain from prior phases.

## 19. Recommendation for Phase 7

First complete the [private human labeling protocol](preference-benchmark-protocol.md):
50+ decisive training choices (ideally 100+), separate held-out groups, independently graded
relevance/favorites, a small deliberate repeat sample, and a genuinely blind new-event final
test if feasible. Judge C against A AND B, inspect favorite losses and noisy/low-light/blur/
emotional-photo failures, report grouped intervals and paired wins/losses. Keep C optional and
inactive if it does not improve. Any Phase 7 scope should be based on those real results.
**Phase 7 has not begun.**
