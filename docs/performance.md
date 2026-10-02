# Performance

Phase 5 ranking/shortlist timings and scopes are in the [Phase 5 report](phase5-report.md#13-performance),
benchmarks/phase5-performance.json and benchmarks/phase5-cached-performance.json.
Cached vector ranking excludes inference and original decoding; larger records repeat local
source metadata to measure scale rather than new-photo accuracy.


Phase 4 event CPU, memory and embedding-reuse measurements are in the
[Phase 4 report](phase4-report.md#14-runtime-and-memory) and benchmarks/phase4-image-performance.json.
The 5,000-record metadata probe uses preloaded synthetic vectors and excludes inference.


Phase 3 distinguishes cold inference, grouping and warm cached scans in
[the Phase 3 report](phase3-report.md) and benchmarks/phase3-performance.json. Reproduce with
photocull benchmark-embeddings after explicit model setup. The Phase 2 0.81-second grouping
measurement does not include model startup or embedding inference.

Phase 2 measurements and scope are in [the completion report](phase2-report.md#14-performance)
and `benchmarks/phase2-performance.json`. Reproduce with `photocull benchmark-duplicates`.

## Historical Phase 1 measurements

Run `.venv/bin/photocull benchmark --extra 300` to generate fixtures in a new temporary directory,
perform cold/warm analysis, print JSON and discard that benchmark's own temporary data. The command
never uses user photos. Stage timing includes database writes within quality/hash/thumbnail stages;
scan timing includes discovery, decoding, metadata and content SHA-256. Total additionally includes
orchestration and cache lookups. Synthetic fixture creation occurs before timing.

The recorded first benchmark is `benchmarks/phase1.json`: Python 3.13.6, macOS ARM64; 317 readable
images, one intentionally corrupt image, one unsupported file. Most images are 256×256, with smaller
resize/crop/orientation fixtures. This is not a full-resolution camera-roll benchmark.

| Stage | Cold seconds | Warm seconds |
| --- | ---: | ---: |
| Scan/decode/metadata/SHA-256 | 0.529 | 0.006 |
| Technical indicators | 0.609 | 0 |
| Perceptual hashes | 0.093 | 0 |
| Thumbnails | 0.165 | 0 |
| Total pipeline | 1.488 | 0.095 |

Cold throughput: 213 readable photos/s. Warm: 3,351 readable photos/s with 317 full-photo cache hits
and 951 component hits. The corrupt input is retried and remains an explicit isolated failure.
These are single-run measurements with warm OS filesystem caches, not a statistical speed guarantee.
Initialization/import time is not included. Latest reproduction may differ from this recorded run.

The pipeline processes one decoded image at a time; quality uses a bounded 1024 edge, thumbnails
512 edge, hashes at most 32×32. Inputs above 80 million pixels are refused by default. A large
allowed image still uses substantial memory while decoded, so 8 GB hardware needs conservative
limits. Candidate path discovery and UI result metadata scale linearly; no pairwise matrix exists.
Full-resolution latency, peak RSS, memory-pressure behavior and Windows/Linux performance are not
measured in Phase 1. Future benchmarking should add megapixel JPEG/WEBP inputs, cold disk reads,
repeat runs and peak memory before claiming consumer camera-roll performance.


Phase 6 model fit uses only 15 columns. See phase6-offline-integration.json for measured
full tuning/30 group-bootstrap fits/persistence and warm reload; phase6-simulated-evaluation.json
contains bare 100-comparison fit and 368-photo inference timings. These measure metadata
learning/ranking, not image decoding/scan latency or public hosting capacity. No new dependencies.


## Phase 7 product benchmarks

See [Phase 7 report](phase7-report.md#10-performance-results) for every measured stage,
cold/warm timing, startup scope, memory and cache size. Raw evidence: benchmarks/phase7-performance.json.
These generated fixtures do not establish public Cloud or human camera-roll throughput.
