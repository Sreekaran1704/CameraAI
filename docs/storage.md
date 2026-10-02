# SQLite and cache

Migration 1 lives in `storage.py`; migration 2 lives in `duplicate_storage.py`. Both apply
transactionally, upgrading existing caches to SQLite `PRAGMA user_version=2`. Newer unsupported
schemas are refused. Phase 3 adds transactional migration 3 from embeddings.py, advancing to
schema 3 with embedding_records. Model/checksum/preprocessing metadata and local NPY references
are persisted; vectors remain outside SQLite. Clearing removes these records and vectors while
preserving model weights. See [embedding provenance](embeddings.md).
Foreign keys are enabled, WAL requested, busy timeout 10 seconds, writes short and serialized.

| Table | Key / contents |
| --- | --- |
| source_photos | Integer ID; unique resolved path; current fingerprint, SHA-256, metadata JSON, update time. |
| scan_runs | UUID; root, mode, state, app version, configuration, progress/timings, cancellation, worker PID. |
| run_photos | Run + photo key; fingerprint observed by that run. |
| analysis_versions | Canonical identity; component, algorithm version, parameter hash, parameter JSON. |
| quality_measurements | Photo + fingerprint + analysis identity; raw/normalized values, warnings, score, generated time. |
| perceptual_hashes | Same provenance key; pHash/dHash/aHash and generated time. |
| thumbnail_metadata | Same provenance key; local path, dimensions, cache key, generated time. |
| processing_failures | Run, path, stage, exception type/message, generated time. |
| user_decisions | Photo ID, constrained favorite/keep/review/reject value, updated time; foundation only. |

Each run saves the actual component identities in progress. Historical results select those IDs
even if configuration or numerical libraries later change. Source metadata tracks the latest
scan; old run membership retains fingerprints, and results whose live files changed are flagged.
It does not snapshot old originals or preserve their historical EXIF indefinitely.

## Fingerprints and invalidation

Phase 2 adds `duplicate_runs`, `duplicate_scan_links`, `similarity_pairs`, `duplicate_groups`,
`duplicate_members`, `not_duplicate_pairs` and `not_duplicate_groups`. Runs retain analysis/config
identity; pairs and members retain source fingerprints and component versions. Only useful
positive evidence is persisted. Corrections are fingerprint-scoped and survive derived-cache
clearing; duplicate runs, links, pairs, groups and memberships are removed by clearing.

Fast fingerprint = SHA-256 of canonical JSON containing resolved path, byte size and nanosecond
mtime. This is a metadata fingerprint, distinct from the SHA-256 of file bytes. First observation
and changed fast fingerprints calculate content SHA-256 while streaming 1 MiB blocks. Unchanged
sources reuse SHA-256. Invalidated analysis parameters recompute that component without rehashing
unchanged file content. `--thorough` rehashes and recomputes all components.

The fast fingerprint cannot detect a deliberately restored mtime with identical file size.
Use a thorough rescan for archival assurance. Source changes during reads/computation are
isolated failures. File timestamps and cache checks cannot eliminate adversarial filesystem races.

Quality/hash cache keys include source fingerprint, component/algorithm version, parameter hash,
and relevant Pillow/NumPy/OpenCV versions. Thumbnail keys additionally include edge, JPEG quality,
orientation handling and interpolation. Missing thumbnail files regenerate. Sources exceeding a
newly lowered pixel limit are rejected even if previously cached. No result is valid solely because
its path exists.

## Paths and clearing

The marked cache contains metadata.db, thumbnails/, embeddings/, models/, jobs/ and logs/.
Models are populated only by explicit setup; embeddings only by enabled inference. Jobs
remain application-owned worker metadata. No originals are copied.
Thumbnails are bounded, orientation-correct RGB JPEGs; EXIF is not copied into them. Writes use
a same-directory temporary file, flush/fsync and atomic replace.

Clear Derived Cache removes measurements, hashes, thumbnail records and owned thumbnail/embedding
files. Analysis-version metadata, source records/content hashes, run history, failures, logs and
decisions remain. No full reset is exposed. It refuses root/home/nonmarked directories, symlinked
ancestors/children, unexpected derived filenames, overlap with registered sources, or an active
pipeline lock. Tests assert original file bytes and decisions survive clearing.

Changed originals can leave obsolete thumbnail files until clearing; automatic eviction is deferred.
Duplicate Review paginates bounded thumbnails, avoiding full-resolution image grids.


## Phase 4 event state

Migration 4 in event_storage.py upgrades transactionally to schema 4. event_runs contains
versioned automatic snapshots; event_scan_links links scan history to its current snapshot.
manual_events stores edited names, and event_overrides stores photo/fingerprint membership
or manual removal. Automatic reruns overlay those edits; changed fingerprints flag conflicts.
Clearing removes automatic snapshots/links but preserves manual edits. Event identity includes
algorithm, parameters, source/component versions, timestamp provenance, numerical runtime, and
optional embedding identity. No original pixels or vectors are stored in event tables.


## Phase 5 ranking state

Transactional migration 5 adds ranking_results keyed by analysis and context/input signature.
Keys include algorithm, parameters, NumPy runtime, source/component fingerprints, actual cached
vector bytes, known duplicate/burst groups and event membership/coverage. Manual membership
changes invalidate affected recommendations. Names and labels are read live for display/export;
favorite labels never affect scores. Clearing removes ranking snapshots, preserving manual
events and user decisions. No pixels or new embedding vectors are stored in ranking tables.


## Phase 6 (schema 6)

preference_feedback stores feature snapshots, canonical pair IDs, explicit choice, connected
group/partition, repeat flag and timestamps. preference_revisions supports correction/undo.
preference_models holds versioned JSON coefficients, training mean/scale, L2/alpha, timestamp,
feature names/version, seed, train/development/holdout group identifiers, validation metrics and
bootstrap sign stability. No executable serialization is used. preference_partitions stores
sticky partition AND historical component identity per source ID/fingerprint.

The historical component ledger prevents manual event splitting from leaking correlated photos
into inner development groups. Merging train and holdout components moves the entire component
to holdout. Corrected feedback invalidates models; changed source fingerprint/analysis/scalars
excludes stale examples. Model cache identity includes current examples/group allocations and
algorithm/feature version. Reset clears only preference tables and reclaims SQLite pages.
