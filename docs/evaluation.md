# Phase 1 evaluation

Fixtures are generated locally with seed 1704 and dataset identity `synthetic_v1`; no downloaded
or copyrighted photos. Generation refuses nonempty destinations. The set has 18 supported image
files (17 readable, one intentionally corrupt) and one unsupported text file:
checkerboard, Gaussian-blurred checkerboard, dark/bright/normal flat images, low/high contrast,
noise, resized/cropped/re-encoded variants, exact copy, lossless WEBP, EXIF rotation and three
EXIF capture-time/timezone burst fixtures. Extras create repeatable noisy images for benchmarking.

Automated comparisons establish sharpness(sharp)>sharpness(blurred), endpoint-exposure fractions
above normal, high contrast>low contrast, and noise residual above flat normal. Exact-copy hashes
match, resized/re-encoded checkerboard hash distances stay within explicit fixture-specific
tolerances, and clockwise EXIF orientation swaps 80×40 to 40×80. Tests cover corruption isolation,
unreadable inputs, source changes, cancellation/recovery, metadata/version invalidation, SQLite
migration, original-preserving cleanup, CLI and Streamlit pages, and network-independent analysis.

Generating two independent sets and comparing every byte SHA-256 checks fixture determinism on
the installed decoder/encoder versions. Across Pillow versions encoded file bytes may change;
use the environment snapshot and dataset version to reproduce experiments.

No human accuracy, duplicate precision/recall, semantic accuracy or aesthetics claim is made.
Phase 2 duplicate evaluation is documented in [duplicate-evaluation.md](duplicate-evaluation.md).
Ranking/clustering/personalization harnesses remain deferred.
Future real-world evaluation should store labels locally, document consent/licensing and split
by independent capture groups/events to prevent near-identical train/test leakage.
