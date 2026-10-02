# Architecture through Phase 6

`Config` validates TOML and provides serializable snapshots. `PhotoScanner` discovers files,
validates decoders and extracts metadata. `QualityAnalyzer`, `PerceptualHashService`, and
`ThumbnailService` perform independent, versioned computations. `Repository` owns SQLite
migration and transactional writes. `Cache` owns paths, process locking and guarded cleanup.
`PipelineRunner` functionality lives in `pipeline.py`; UI/CLI are consumers.

Discovery → metadata/decode/SHA-256 → quality → hashes → thumbnail → run membership.
Phase 2 then runs duplicate/burst detection under the same worker lock. The pure `similarity.py`
engine consumes path-independent feature DTOs; `duplicates.py` adapts filesystem/cache results
and `duplicate_storage.py` persists versioned evidence. Future in-memory sources can use this
engine without filesystem paths.
Per-file exceptions are persisted and do not abort other files. Errors before the file loop
mark the run failed. The pipeline fingerprints again after reading and before completion.
Partial component results can be reused on a subsequent run only when their provenance matches.

## Background jobs

The UI starts `python -m photocull.worker CACHE RUN_ID` with an argument list, never a shell.
The worker loads the persisted configuration and acquires an exclusive nonblocking POSIX file
lock. It writes short SQLite transactions after each file; the UI polls using a timed fragment.
Workers do not call Streamlit. CLI analysis uses the same pipeline synchronously.

Run states: queued, running, completed, cancelled, failed, interrupted. Discovery is cancellable;
processing cancellation is checked between files. Decoding an individual large file cannot be
interrupted immediately. Completed results survive cancellation, UI reruns and UI restart.
Restart a scan to recover completed work; dead registered worker PIDs are marked interrupted.
PID-based recovery is basic: PID reuse can delay interruption detection, and there is no
automatic watchdog restart. Results remain available independently of worker status.

One cache processes one job at a time. A conflicting run fails clearly with a busy error.
Cleanup uses the same exclusive lock. SQLite WAL supports concurrent UI readers. Connection
objects are not shared across processes or UI execution threads.

## Future boundaries

Phase 7 and later implementations are not included. Phase 3's optional EmbeddingService and
HybridEngine are documented in [embeddings.md](embeddings.md). Hash-only remains the default.
The embedding_records table supports coexisting model identities. Analysis versions record
component/algorithm/parameter identity; embedding cache identity includes model checkpoint
checksum, preprocessing and numerical runtime. Future encoders can add registry entries without
a singleton embedding field. Phase 4 adds the independent event engine in events.py, automatic/manual storage in
event_storage.py, evaluation and performance adapters, and ui/event_review.py.
Event discovery follows duplicate detection under the same pipeline lock. Default event analysis
is time-only; optional visual event choice does not activate hybrid duplicates. Phase 5 adds ranking.py, cache-only ranking_service.py, ranking_evaluation.py and
ui/best_photos.py. Ranking follows event discovery and uses existing metadata/vectors.
Generic A/B do not learn preferences. Phase 6 adds optional explicit feedback learning.
See [Phase 4 report](phase4-report.md) for event discovery.


Phase 6 adds preferences.py (15 scalar features, bounded contextual pairs, NumPy L2 logistic
model and separate Ranking C), preference_storage.py (schema 6, local/session feedback,
history, sticky connected partitions and model JSON), preference_evaluation.py (offline
grouped learning curves and experiments), and ui/preferences.py. The generic ranking_v1.2
implementation and Phase 5 benchmark remain frozen. C applies the existing B shortlist
diversity/known-group suppression after personalized relevance scoring. No Phase 7 work.
