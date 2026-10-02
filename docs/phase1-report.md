# PhotoCull Phase 1 completion report

Completed October 1, 2026 (America/Chicago). Phase 2 has not begun. Nothing was staged, committed
or pushed. The workspace was initially empty; all project files listed below are newly created.

## 1. Implementation summary

Local Python package, configurable CLI, Streamlit Import/Overview/Cache pages, recursive scanner,
EXIF metadata, read-only SHA-256 foundation, thumbnails, eleven technical indicator categories,
perceptual hashes, SQLite provenance/migration, subprocess jobs, cancellation/recovery, safe cache
clear, synthetic evaluation and cold/warm benchmark. CPU only; no model/inference dependencies.

## 2. Repository tree

```text
CameraAI/
├── pyproject.toml
├── requirements-lock.txt
├── README.md
├── .gitignore
├── .streamlit/config.toml
├── configs/default.toml
├── src/photocull/
│   ├── __init__.py
│   ├── benchmark.py
│   ├── cache.py
│   ├── cli.py
│   ├── config.py
│   ├── fixtures.py
│   ├── hashing.py
│   ├── jobs.py
│   ├── pipeline.py
│   ├── provenance.py
│   ├── quality.py
│   ├── scanner.py
│   ├── storage.py
│   ├── thumbnails.py
│   ├── worker.py
│   └── ui/app.py
├── tests/
│   ├── conftest.py
│   ├── test_features.py
│   ├── test_integration.py
│   ├── test_scanner.py
│   └── test_storage_cache.py
├── benchmarks/
│   ├── phase1.json
│   ├── dependency-audit.json
│   └── overview.jpg
└── docs/
    ├── architecture.md
    ├── evaluation.md
    ├── features.md
    ├── hashing.md
    ├── limitations.md
    ├── performance.md
    ├── phase1-report.md
    ├── privacy.md
    ├── setup.md
    └── storage.md
```

Ignored local runtime artifacts also exist: .venv/, src/photocull.egg-info/, .photocull/,
benchmark-output/photos/, Python/test/lint caches. These contain dependencies or generated test
images, not imported user photographs.

## 3. SQLite schema

Schema version 1 has nine tables: source_photos, scan_runs, run_photos, analysis_versions,
quality_measurements, perceptual_hashes, thumbnail_metadata, processing_failures,
user_decisions.
See storage.md for keys/fields and storage.py for executable SQL. WAL, foreign keys, short
transactions, canonical analysis identities and UTC generation timestamps are enabled.
Quality/hash/thumbnail results use the composite key (photo_id, fingerprint, analysis_id).

## 4. Fingerprints

Fast identity hashes resolved path + byte size + nanosecond mtime. First/changed observations
calculate streaming content SHA-256; compatible unchanged files reuse it. Parameter-only changes
recompute affected analysis without unnecessary content hashing. --thorough rehashes/recomputes.
Repeated stat checks isolate ordinary changes during reading/analysis. Preserved size+mtime is a
documented fast-fingerprint limitation.

## 5. Implemented quality features

Sharpness, exposure, underexposure, overexposure, luminance/channel clipping, contrast, resolution,
aspect ratio, entropy, noise proxy and colorfulness. Raw values, analysis dimensions, normalized
components, warnings and provenance are persisted separately. Thresholds are in validated TOML
configuration, not UI code. features.md defines all formulas and limitations.

## 6. technical_quality_v1

Version A is exactly 0.40 sharpness + 0.25 exposure + 0.20 contrast + 0.15 resolution, using
normalized components. Approved weights cannot be silently changed under the v1 identity.
The UI calls this Technical Quality and distinguishes it from artistic quality. No ranking
or recommendation engine has been implemented.

## 7. Hashing

64-bit aHash, dHash and DCT pHash, stored as hex. Lanczos resizing; grayscale conversion;
pHash DC bit excluded/zeroed. Stored component/version/parameters include numerical library
versions. Exact-copy equality and fixture-specific transform tolerance are tested. No grouping.

## 8. Background jobs

Detached Python subprocesses load SQLite run configuration and process independently of Streamlit.
Persisted status/progress/counts/timings are polled by the UI. Cooperative cancellation happens
between files; completed components survive interruption. Dead registered worker PIDs are marked
interrupted; a new scan reuses completed outputs. One exclusive cache lock prevents competing
pipelines or cleanup. No daemon scheduler, watchdog or cloud workers.

## 9. Cache behavior

Dedicated ownership-marked cache with database, atomic bounded JPEG thumbnails and reserved future
directories. Identity combines source fingerprint, component/algorithm, parameters and runtime
versions. Clear Derived Cache preserves originals, source metadata and decisions, refuses unsafe
paths/symlinks/unexpected files/registered source overlap and busy processing. Tests verify byte
preservation. Cleanup is not forensic erasure.

## 10. Privacy

No application remote APIs, uploads, model downloads, cloud services or telemetry. Localhost binding,
usage-stats disabled, bundled fonts, local thumbnails, minimal toolbar, restrictive new cache
permissions. Python outbound connections are blocked during tests. Browser workflow was checked
using generated fixtures only; no real user photos were inspected. No full browser packet capture
was performed. Package installation/security audit contact package services separately, with no
photo/application metadata submitted.

## 11. Fixtures and evaluation

Deterministic synthetic_v1: 18 supported files, 17 readable, one corrupt, plus one unsupported
text file. Includes WEBP, crop/resize/re-encode, noise/exposure/contrast, EXIF orientation and
capture-time/timezone fixtures. Relative technical behavior and exact-copy hash equality pass.
Two independent generations produce identical file SHA-256 sets. There is no real-world accuracy
claim or human-label dataset yet.

## 12. Measured benchmark

317 readable small synthetic images, one corrupt, one unsupported on macOS ARM64 / Python 3.13.6:
cold 1.488 s (213 photos/s); warm 0.095 s (3,351 photos/s), 317 full-photo and 951 component hits.
Cold stages: scanning 0.529 s, quality 0.609 s, hashes 0.093 s, thumbnails 0.165 s.
Full JSON is benchmarks/phase1.json. These single-run 256-pixel fixtures do not establish
high-resolution camera-roll performance; import/setup/fixture generation are excluded.

## 13. Validation results

| Check | Result |
| --- | --- |
| Unit + integration suite | 37 tests passed with network-denial fixtures. |
| Ruff lint | Passed. |
| Ruff formatting | Passed; 21 Python files checked. |
| Python compileall | Passed. |
| pip dependency consistency | No broken requirements. |
| Vulnerability audit | No known vulnerabilities after upgrading local pip 25.2 → 26.2.1. |
| Fixture determinism | Byte-hash equality passed. |
| Scan/analyze CLI, cache status/clear | Passed. |
| Fingerprint/config/algorithm invalidation | Passed. |
| Path safety / original preservation | Passed. |
| SQLite migration rerun | Passed. |
| Cancellation / persisted worker results / dead worker recovery | Passed. |
| Source changed mid-read or mid-analysis | Isolated failure tests passed. |
| Offline child-process CLI | Passed with Python socket connections denied. |
| Streamlit AppTest | Import, Overview and Cache passed. |
| Actual Streamlit startup/browser | Served localhost:8517; fixture Import and Overview verified. |
| Type checking | Not configured; not claimed. |

## 14. Warnings and limitations

The corrupt fixture intentionally emits UnidentifiedImageError warnings. A pip warning noted that
the host's shared cache directory was unavailable in the filesystem sandbox; pip disabled that
download cache and installation/checks still succeeded. Initial startup could not bind inside the
sandbox; authorized localhost startup succeeded outside it. Port 8501 was already occupied, so
the smoke test used 8517. Initial audit found 12 advisory entries (including duplicates) affecting
pip only; the final audit reports none after updating the virtual environment.

No HEIC/RAW, GPU, embeddings, duplicates, events, aesthetic judgments, rankings or personalization.
POSIX locking limits this version to macOS/Linux; only macOS has been tested. No memory benchmark
or large megapixel-photo validation. PID recovery is basic and cleanup has trusted-user filesystem
assumptions. See limitations.md for the complete scope.

## 15. Created/changed files

Every repository file in the tree above is new. No preexisting source files were changed. Local
runtime dependencies were installed in .venv only, including an audited pip upgrade. Generated
images and application caches are ignored; no staging, commits, pushes or Git initialization.

## 16. Phase 2 considerations

Before implementing duplicate groups, add privately labeled exact/near/similar-negative pairs,
calibrate conservative hash/time/dimension thresholds, prevent transitive-chain overgrouping,
and compare precision/recall/false positives independently. Content SHA-256 and EXIF timestamp
provenance are ready. Source mutation APIs remain excluded. Phase 2 awaits separate authorization.
