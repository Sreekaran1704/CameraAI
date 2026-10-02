# Private human preference benchmark

Phase 6 currently has **zero real human labels**. Simulated results test the mechanics and
do not answer whether PhotoCull improves this user's rankings.

1. Analyze a private local library with several independent events/bursts. Avoid selecting
   events based on algorithm success. Keep photos on the local machine.
2. Open Preferences → Teach PhotoCull My Taste in Local Edition. The partition ledger
   reserves about 20% of independent connected components as held-out groups before labels.
   Events and known duplicate/burst groups are unioned transitively. Historical components
   remain connected after manual splitting. Mixed partition merges are quarantined as
   holdout; they never leak back into training.
3. Collect at least **50 decisive training choices across 3 groups**, ideally 100+.
   Also collect **at least 10 decisive held-out choices across 2 groups**.
   Fifty total clicks are not fifty training examples. Ties, skips and consistency repeats
   are recorded but excluded from binary learning and the activation count.
4. In Held-out evaluation mode, label without consulting Best Photos or scores for those
   groups. Photo A/B sides alternate to reduce fixed-side bias. Choose Tie when neither is
   preferable; Skip when a comparison is not meaningful.
5. Deliberately repeat around 5% of prior choices later. Do not deliberately reproduce
   an earlier answer. Agreement is descriptive, not a judgment of the user. Undo or correct
   mistakes in Review and correct previous choices before analysis.
6. For NDCG/favorite recall, independently grade every photo in the chosen held-out groups:
   relevance 0–3 and favorite true/false. Complete the labels before examining algorithms.
   Binary pair choices alone do not define a complete graded ranking.
   Create a private JSON object keyed by local photo ID:
   `{"123": {"relevance": 3, "favorite": true}, "124": {"relevance": 1, "favorite": false}}`.
   Never upload this file. No algorithm should infer those labels for you.
7. Run the offline evaluator locally:

   ```sh
   .venv/bin/python -m photocull.preference_evaluation --cache-dir /absolute/cache --grades /private/local-grades.json --output /private/local-result.json
   ```

   The evaluator denies outbound Python sockets. It reports grouped A/B/C pair accuracy,
   bootstrap intervals, paired group wins/losses and learning curves at 10/20/30/50/75/100
   training examples. Graded metrics use within-group raw scores at K=3.
8. For a stronger final experiment, reserve additional entirely new events after development
   and hide their labels until the comparison is finalized. The app's evolving validation
   groups are repeatedly reused; their intervals/tests are descriptive and cannot be treated
   as a pristine final significance result. Stop tuning after viewing the final test.
9. Record the feature/model version, seed, alpha/L2 selection, grouping, number of usable
   pairs/groups, missing/changed-source exclusions, ties/skips and repeat agreement.
   Compare improvements AND failures, particularly emotional low-quality favorites, noise,
   intentional blur, low light, and event coverage.
10. Leave C inactive if evidence is insufficient or it does not beat both baselines. A nominal
    improvement on only two groups is exploratory; it is not a reliable universal taste claim.

Only local IDs, fingerprints, feature scalars, group assignments and preference labels are
persisted for learning. No new image copies, full embeddings, identities or remote training.
Local database permissions are 0600 in the existing private cache. This is not encryption.
Reset removes learning tables/model; photo analysis, favorites and manual events remain.
SQLite checkpoint/VACUUM reclaims database pages; forensic deletion from backups/SSD is not promised.
Web Demo uses session-only feedback/model (force with PHOTOCULL_WEB_DEMO=1); no public deployment
was performed. Session data remains in server RAM while the session is alive.

Phase 7 supersedes the preference-only demo flag: deploy streamlit_app.py for the
upload-only memory edition. Never deploy the local folder UI. See deployment.md.
