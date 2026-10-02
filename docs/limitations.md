# Current limitations

- No standalone semantic recommendations, OCR, face recognition, photo deletion/moving
  or cloud services. Personalized ranking is optional and unvalidated for human taste.
- JPG/JPEG, PNG, WEBP only. HEIC/RAW are unsupported; animated files use the first frame.
- CPU technical measurements are provisional and scene-dependent. Noise is a proxy; blur
  warnings can flag smooth scenes, exposure warnings can flag intentional lighting.
- Metadata fingerprints cannot detect byte changes with preserved size/mtime; use --thorough.
- No forced cancellation inside decoding of one file. Recovery reuses completed components,
  not a pixel-level checkpoint. PID recovery has no watchdog and can be affected by PID reuse.
- POSIX locking currently requires macOS/Linux. Only macOS was tested. No Windows guarantee.
- Historical source metadata is not immutable; old run fingerprints are retained and changed
  sources are flagged. Derived files can accumulate until explicitly cleared.
- No app encryption, authentication, hostile-filesystem race defense or forensic erasure.
- Python socket-denial tests are not full browser packet capture or third-party code audit.
- No static type checker configured. No real-photo accuracy or high-resolution speed claims.
- Conservative rules miss crops and rotations. Low-texture inputs are excluded from perceptual
  recommendations because their hashes collide easily. Confidence scores are uncalibrated heuristics.
- Synthetic labeled pairs are not exhaustive real-photo ground truth. Complete-link burst groups
  split longer sequences; mixed or missing timestamp tiers reduce coverage. Filesystem fallback
  is disabled by default.
- BK-tree search can degrade on colliding hashes; work/group caps explicitly report incomplete
  search. Exact-bucket candidate collapsing can reduce burst coverage.
- Savings estimate file bytes rather than allocated disk blocks; hard links are excluded.
- Phase 3 embeddings are experimental: both hybrids fell below 97% precision on expanded hard
  negatives. Hash-only is the default. Approximate retrieval and complete-link grouping reduce
  end-to-end recall; pair-rule metrics are not group accuracy.
- Optional inference adds hundreds of MiB of memory. MPS fallback has unit coverage but real
  measurements validate CPU only. No free-hosted or high-resolution camera-roll benchmark.

Phase 4 event quality is synthetic only. Time-only can overmerge nearby occasions; visual
methods can oversplit travel. Timestamp tiers stay separate, so mixed camera clocks need manual
corrections. Filesystem grouping is low confidence; this is independent of disabled filesystem
burst inference. See [event limitations and results](phase4-report.md).

Phase 5 A/B ranking is heuristic and synthetic-only. B did not improve held-out NDCG,
and technically sharp noise can dominate pooled shortlists. See [ranking results and
limitations](phase5-report.md); no aesthetic or emotional preference claim is supported.


Phase 6 personalized benefit is **unvalidated for this user**: no human choices exist yet.
Simulated feature-dependent preferences are a controlled mechanics exercise. C can improve
pairwise/NDCG while reducing favorite recall. The 50-training-pair floor is provisional;
activation also requires grouped held-out improvement, which can still be noisy with few
groups. Validation groups reused over time are not an untouched final significance test.
Linear coefficients are conditional correlated associations, not causal taste explanations;
logistic likelihoods are not calibrated confidence. Historical grouping is conservative and
can make large connected libraries ineligible. The noise-guard experiment succeeded only on
small synthetic random-noise pairs and was not adopted into frozen technical_quality_v1.
