# PhotoCull — Phase 7

See [the photographic demo dataset notes](docs/demo-dataset.md) for sample examples,
generation provenance, and measured behavior.

**Local Edition: your photos stay on this device.** PhotoCull reads a local folder and exposes measurable
technical-quality indicators, EXIF-aware previews, and explained exact/near duplicate and burst
groups. Originals are never modified. Optional local MobileNet/TinyCLIP embeddings support an
experimental hybrid rule. Hash-only stays the default: expanded hard-negative precision did not
meet the acceptance target. Local event discovery adds neutral event groups, uncertainty, representatives, and persistent manual corrections. Explainable ranking and diverse highlights now support event, burst and duplicate review.
Optional explicit local preference learning is available. No cloud inference or photo deletion.

Duplicate Review recommends a technical representative, records Keep/Favorite/Review Later and
Not Duplicate corrections, and separates exact reclaimable bytes from hypothetical near savings.
Bursts identify a photographic moment and do not imply redundancy.


## Two editions

**Local Edition** scans folders on your device, retains a private SQLite cache and persistent
decisions/preferences, and works offline after installation. **Web Demo** accepts explicit
browser uploads only and uses bounded, memory-only sessions. Uploaded images are processed
temporarily for this session and are not intentionally persisted by PhotoCull. Images reach
the demo server; the web edition does not claim device-only privacy.

Try the 12 generated, CC0 photographic samples using **Try Demo Without Uploading Photos**.
The demo caps sessions at 30 images, 15 MiB/image, 60 MiB cumulative uploads and 8 MP/image.
No hosted database, accounts, paid APIs or remote inference are needed.

Launch the web edition from the project root:

```sh
.venv/bin/streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port 8518 --browser.gatherUsageStats false --server.headless true
```

A clean web-only environment can install `requirements.txt`; the Local Edition uses
the editable installation below. Python 3.13 is the verified deployment runtime.
Use `?embed=true&compact=true` for portfolio presentation.
See [Phase 7 completion report](docs/phase7-report.md),
[deployment steps](docs/deployment.md), [portfolio embed](docs/portfolio-embed.md),
[privacy differences](docs/privacy.md) and [verified metrics](docs/verified-results.md).
Public deployment has not been performed.

## Quick start

Python 3.11+ on macOS or Linux; CPU only. This implementation uses POSIX file locking.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev,events]'
.venv/bin/streamlit run src/photocull/ui/app.py --server.address 127.0.0.1 --browser.gatherUsageStats false --server.headless true
```

Open the localhost URL printed by Streamlit. Enter an absolute path to a photo folder.
Supported formats: JPG/JPEG, PNG, WEBP. HEIC and RAW are unsupported in this phase.
Animated WEBP/PNG uses the first frame only. EXIF orientation is applied before measurement.

Installation needs a package source once. Analysis and tests need no network or model download.
The runtime defaults to `~/.photocull/`; it must be separate from the source folder, without
symlinked ancestors. Override UI paths with `PHOTOCULL_CACHE_DIR` and `PHOTOCULL_CONFIG`.

## Best Photos

Best Photos provides Best 10/20, event/burst/duplicate recommendations and Favorites.
A uses Technical Quality v1. B adds representation, guarded uniqueness, similarity penalties
and soft coverage. Known duplicate/burst groups contribute at most one recommendation.
Event pages show Recommended Highlights. Every card has local Keep/Favorite/Review controls.

CSV/JSON export contains source paths, rank, event, metrics, explanations and user labels.
It never moves or copies originals. Ranking uses hashes by default; optional existing vectors
are read from cache only. It performs no inference, model setup or preference learning.

```sh
.venv/bin/python -m photocull.ranking_evaluation --generate benchmark-output/my-ranking-fixtures
.venv/bin/python -m photocull.ranking_evaluation --manifest benchmark-output/my-ranking-fixtures/manifest.json
.venv/bin/python -m photocull.ranking_evaluation --performance
```

The [Phase 5 report](docs/phase5-report.md) reports the mixed A/B results and strong limitations.
Synthetic authored preferences do not establish real-world or emotional/aesthetic accuracy.

## Events

The Events page groups likely occasions by capture time with a development-selected two-hour
gap. Timestamp provenance remains separate; filesystem and naive EXIF assignments are marked
low confidence. Rename, move, remove, merge and subset-split edits survive automatic reruns.
The default needs no model. Event representatives provide coverage, not Best Photos ranking.

For optional visual event experiments and evaluation, install both extras and explicitly set
up local weights as described in [embeddings](docs/embeddings.md):

```sh
.venv/bin/pip install -e '.[embeddings,events]'
.venv/bin/photocull event-fixtures benchmark-output/my-event-fixtures
.venv/bin/photocull --cache-dir .photocull evaluate-events --manifest benchmark-output/my-event-fixtures/manifest.json
.venv/bin/photocull benchmark-events
.venv/bin/python -m photocull.event_benchmark --evaluation benchmarks/phase4-event-evaluation.json --model-cache .photocull
```

See the [Phase 4 report](docs/phase4-report.md) for held-out metrics, method tradeoffs,
runtime, uncertainty and limitations. These synthetic measurements are not real-world accuracy.

## CLI

Output is sorted-key JSON on stdout; warnings/errors are on stderr. Run IDs and timestamps vary.
Exit codes: 0 completed (possibly with isolated file failures), 1 failed run, 2 invalid input.

```sh
.venv/bin/photocull --cache-dir .photocull scan /absolute/photo/folder
.venv/bin/photocull --cache-dir .photocull analyze /absolute/photo/folder
.venv/bin/photocull --config configs/default.toml --cache-dir .photocull analyze /absolute/photo/folder --thorough
.venv/bin/photocull --cache-dir .photocull cache status
.venv/bin/photocull --cache-dir .photocull cache clear
.venv/bin/photocull fixtures benchmark-output/photos
.venv/bin/photocull benchmark --extra 300
.venv/bin/photocull --cache-dir .photocull duplicates /absolute/photo/folder
.venv/bin/photocull duplicate-fixtures benchmark-output/phase2-v1-new
.venv/bin/photocull evaluate-duplicates
.venv/bin/photocull evaluate-duplicates --manifest /absolute/private/manifest.json --format csv
.venv/bin/photocull benchmark-duplicates
.venv/bin/python -m pip install -e '.[embeddings]'
.venv/bin/photocull --cache-dir .photocull model-setup mobilenet
.venv/bin/photocull --cache-dir .photocull model-setup tinyclip
.venv/bin/photocull --cache-dir .photocull evaluate-hybrid --manifest benchmark-output/phase2-v1/manifest.json --hard-manifest benchmark-output/phase3-hard-v1/manifest.json
.venv/bin/photocull --cache-dir .photocull benchmark-embeddings --evaluation benchmarks/phase3-evaluation.json
```

`scan` validates/decode-checks files, records metadata and SHA-256, but calculates no derived
quality/hash/thumbnail outputs. `analyze` also runs duplicate/burst grouping and Phase 4 events.
`duplicates` runs that same pipeline and includes full detection results in its JSON. Warm analysis
reuses unchanged source metadata and independently valid component results. `--thorough`
rehashes and recomputes every readable file. Fixture generation requires an empty destination.

Cache clearing preserves source records, scan history, decisions, Not Duplicate corrections, manual event edits and
originals; it removes automatic events, duplicate/burst results, derived measurements and application-owned previews.
It refuses busy caches and unsafe paths.
There is no full-reset command and no source-deletion API.

## Validation

```sh
.venv/bin/pytest -q
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/python -m pip check
.venv/bin/python -m compileall -q src
.venv/bin/pip-audit --local --skip-editable --progress-spinner off
```

Tests deny Python socket connections, including a child-process offline CLI test. Dependency
auditing separately contacts a public package advisory service; it sends package identifiers,
never photos or application metadata. Type checking is not configured in this phase.
`requirements-lock.txt` captures the tested environment's exact package versions; it is a
version snapshot, not a cross-platform, hash-verified lockfile. Install it before `-e .` to
recreate the tested versions on a compatible platform. The application's declared dependency
ranges remain in `pyproject.toml`.

## Documentation

- [Setup](docs/setup.md)
- [Architecture and jobs](docs/architecture.md)
- [Privacy](docs/privacy.md)
- [SQLite and cache](docs/storage.md)
- [Technical feature definitions](docs/features.md)
- [Perceptual hashing](docs/hashing.md)
- [Evaluation and fixtures](docs/evaluation.md)
- [Performance](docs/performance.md)
- [Limitations](docs/limitations.md)
- [Duplicate methodology](docs/duplicates.md)
- [Phase 2 evaluation](docs/duplicate-evaluation.md)
- [Phase 2 completion report](docs/phase2-report.md)
- [Local embeddings and hybrid rules](docs/embeddings.md)
- [Phase 3 comparison and completion report](docs/phase3-report.md)
- [Event methodology and Phase 4 report](docs/phase4-report.md)
- [Ranking methodology and Phase 5 report](docs/phase5-report.md)
- [Historical Phase 1 report](docs/phase1-report.md)

Do not interpret Technical Quality v1 as artistic quality. Warnings are inspectable technical
signals, not reasons to delete a photograph. Phase 2's synthetic benchmark measured 98.4% precision
and 71.4% recall for near-pair classification, with one false positive; final groups measured
100%/71.4% on the labeled pairs. This does **not** support a 96%/89% real-world accuracy claim.
Privately labeled real photos are needed before claiming photographic accuracy.


## Phase 6: optional local preference learning

Open **Preferences → Teach PhotoCull My Taste** to compare contextual photo pairs.
Prefer A/B, Tie, Skip, correction and undo are explicit local feedback. C uses 15
interpretable scalars and regularized pairwise logistic regression. A/B remain frozen.

Personalization starts inactive. Activation requires at least 50 decisive training pairs
across 3 connected groups, plus 10 held-out pairs across 2 groups with C accuracy above A
and B. This is exploratory validation, not a promise of human benefit. Ties/skips/repeats
do not count toward training. Best Photos offers Generic and Personalized modes with
generic fallback. Reset removes only preference data/model.

Local Edition persists in schema 6 SQLite. The Phase 7 Web Demo entry point isolates all
photo/feedback/model state in session memory. The older PHOTOCULL_WEB_DEMO preference-only
flag does not make the local folder app safe to publish. No deployment was performed.

[Phase 6 report](docs/phase6-report.md) ·
[Private human benchmark protocol](docs/preference-benchmark-protocol.md) ·
[Simulated learning curve](benchmarks/phase6-learning-curve.svg)

Reproduce the generated-image simulation (not a human study):

```sh
.venv/bin/python -m photocull.preference_evaluation --synthetic-manifest benchmark-output/phase5-ranking-v2/manifest.json --output benchmarks/phase6-simulated-evaluation.json
.venv/bin/python benchmarks/phase6_offline_integration.py
```

After collecting private human labels:

```sh
.venv/bin/python -m photocull.preference_evaluation --cache-dir /absolute/local/cache --output /private/local-evaluation.json
```

Add `--grades /private/photo-grades.json` for complete independently graded held-out
groups. Pair choices alone cannot supply NDCG or favorite recall. Do not publish private outputs.
# CameraAI
