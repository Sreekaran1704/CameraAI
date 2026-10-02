# Phase 2 duplicate and burst methodology

Four relationship types are explicit: EXACT_DUPLICATE, NEAR_DUPLICATE, BURST_GROUP and reserved
VISUALLY_SIMILAR. There are no semantic models, embeddings or deletion actions. SimilarityEngine
accepts PhotoFeatures objects with IDs, hashes, dimensions, quality and timestamps; it does not
open paths. The filesystem adapter reads local analysis and previews. Future in-memory sources
can provide the same features/temporary verification pixels without a filesystem grouping API.

## Exact copies

Group nonempty equal SHA-256 values, not filenames. More than two copies are supported. Each
group stores compact representative-to-member evidence rather than every possible pair. This
is byte equality, not decoded-pixel equality; metadata edits/recompression are near candidates.
Missing hashes never imply equality. Human exclusions can partition or suppress these groups.

## Candidate generation

Collapse exact content to one representative per SHA bucket before perceptual matching. Reject
low-entropy/contrast candidates for perceptual inference. Index unique pHash values with a BK-tree,
whose metric radius avoids prefix bucket boundary misses. Query the maximum configured near/burst
radius; use comparable timestamp windows to skip pixel verification of distant non-near candidates.

With N files and C admitted candidates, exact buckets use O(N) storage/time, index search depends
on hash distribution, and verified comparisons use O(C × 1024). Complete-link checking can add
comparisons within proposed groups. BK-tree queries still have O(N²) worst-case behavior for dense
or adversarial hashes; no universal subquadratic guarantee is claimed. There is no dense similarity
matrix and only useful positive relationships are persisted. Default bounds are 256 candidate
neighbors per photo, 100,000 comparisons total and 128 members per near/burst group. Limits are
reported visibly; matches can be missed when reached. Exact groups are not capped.

## Near rule — duplicates_v1

All conditions must hold:

- pHash Hamming distance ≤2; dHash ≤8 and aHash ≤8 corroborate it.
- Both quality histograms have entropy ≥3 bits and contrast P95−P5 ≥25 luminance units.
- Absolute log aspect-ratio difference ≤0.04 (approximately 4%).
- Normalized grayscale correlation of local 32×32 preview samples ≥0.999.
- Maximum difference between mean RGB chromaticity components ≤0.12 on 0..1 units.
- Comparable EXIF times, when both available, differ by ≤60 seconds.

Local pixel verification is deterministic preprocessing of cached thumbnails: grayscale samples
are centered and unit-normalized; zero-energy samples become zero vectors. Mean chromaticity is
mean RGB minus the mean of those three components. Arrays live temporarily in RAM and are not
persisted as image bytes or model embeddings. Evidence stores only correlation/chroma scalars.
Missing/corrupt/unsafe previews disable perceptual inference for that file while exact SHA remains
usable. Resolution area ratio and dimensions are explanatory measurements, not rejection thresholds
because resizing is a legitimate duplicate transformation. Filename sequence is weak evidence only.

These rules prioritize precision over transformation recall. Slight crops/rotation can fail;
smooth photos and documents can be excluded despite being near duplicates. Similar scenes/poses
can still fool the rule. Byte-exact detection remains available for low-texture files.

## Bursts

Capture-time hierarchy: timezone-aware EXIF, naive EXIF, filesystem fallback. Aware values are
compared as actual instants across offsets; naive values compare only with naive values. Mixed
tiers are treated as incomparable. Naive EXIF assumes comparable camera clocks and carries a
warning. Filesystem fallback is disabled by default; explicit opt-in uses lower heuristic reliability.

Every burst pair must have capture gap ≤5 seconds, pHash≤12, dHash≤18, aHash≤16, log aspect difference
≤0.15, local correlation≥0.70, chroma≤0.12 and the same texture guards. Windows 2/5/10 seconds were
tested on development data; 5 seconds is the smallest with full pair-rule recall there. Capture
timestamps often have second resolution; filenames do not make unreliable timestamps reliable.
Near groups and bursts can overlap, since a moment and redundancy are different concepts.

## Grouping and representatives

Deterministic greedy complete-link grouping: a new member must satisfy the selected rule with
every existing member, not merely the representative or one neighbor. Every group's evidence
contains all tested member pairs and maximum within-group pHash distance. An A–B–C chain cannot
imply A–C membership. This deliberately partitions extended bursts and can lose valid neighbor
pairs across groups. It is not an optimal global partition or an event-clustering algorithm.

Representatives use highest technical_quality_v1, then pixel area, normalized sharpness, exposure,
and stable ID for deterministic ties. Reasons give actual sharper/better-exposed comparison counts.
No aesthetic or uniqueness ranking is implemented. User decisions are annotations, not deletion
authorization, and hypothetical savings assume the recommended representative remains.

Reliability outputs are heuristic: near 0.9, timezone-aware burst 0.8, other allowed burst 0.6.
Exact equality uses 1.0 to signal SHA evidence, not a calibrated probability of photographic merit.

## Savings and corrections

Exact savings sum all alternative file sizes while retaining one representative. Near savings
operate only on retained canonical files, excluding exact-copy alternatives, so exact and near
estimates do not count the same file bytes twice. Bursts do not contribute savings. Known hardlinks
are excluded conservatively; filesystem deduplication/compression/snapshots can change actual space.

Keep/Favorite/Review Later persist in existing decisions. Mark a member Not Duplicate blocks it
against every current group peer, scoped to both fingerprints. Mark a group Not Duplicate suppresses
that exact membership/fingerprint signature. New members or edited files may need new review.
Corrections survive derived-cache clearing and enter the detection cache identity. UI hides stale
group/savings results after source changes or pending corrections. No file is deleted or moved.
