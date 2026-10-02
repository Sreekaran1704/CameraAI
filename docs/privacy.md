# Privacy model

## Local Edition

Your photos stay on this device. Local Edition performs no remote inference and has no cloud storage,
hosted vector database, analytics, or upload controls. Optional explicit model-setup commands
download public weights; ordinary scans never download. It reads originals only.
UI previews are locally generated thumbnails served by the loopback Streamlit server.
No remote fonts, CSS, images or chart datasets are configured. Streamlit's default font files
are bundled and served locally; usage telemetry is disabled in configuration and launch examples.
The minimal toolbar hides cloud deployment controls.
Browser error details are hidden to prevent debugging links containing private tracebacks.
Duplicate evidence, groups and corrections remain in local SQLite. Pixel verification uses
temporary thumbnail arrays in memory; no pixels are sent to a service.

The application writes local filenames, paths, timestamps, technical measurements, hashes,
failure messages and thumbnails to its dedicated cache. It extracts orientation and capture
time/timezone, not GPS or identity information. The database contains no image bytes.
Worker warnings omit source names; detailed failures remain in local SQLite. CLI stdout and UI
history intentionally expose local metadata to the user; protect exported terminal logs.

Tests deny Python socket connections. A subprocess test also injects denial before CLI imports.
These verify network-independent Python analysis; they are not a packet capture, an OS firewall
or a guarantee against future dependency behavior. Browser verification is documented in the
completion report. Loopback traffic is required for the UI and is not an external photo upload.

Package installation and the separately invoked dependency auditor contact package services.
The auditor sends package names/versions only. Neither operation reads photos or the database.
After installation, runtime analysis works offline. Hash-only requires no weights; optional
embeddings require prior explicit local setup. Vector caches contain private derived features,
not image bytes, and must be protected like other local analysis data.

New cache directories use mode 0700, SQLite/worker logs use 0600, and atomic thumbnails inherit
temporary-file mode 0600. Existing directories are not silently permission-modified. Data is
not encrypted by PhotoCull; use OS disk encryption and a trusted local account. Local backups,
OS indexing and any sync service covering the chosen cache are outside PhotoCull's control.

Clear Derived Cache is logical removal, not forensic secure erasure. SQLite checkpoint/VACUUM
attempts reclaiming derived pages; SSD snapshots/backups can retain previous data. Source
metadata, scan history, failure messages and user decisions remain. There is no full reset.

Safety assumes a trusted local user and no hostile concurrent filesystem replacement. Paths
are checked for symlinks, ownership markers, source/cache overlap and generated filenames;
this is not a complete defense against an attacker racing filesystem changes on the same account.


Event assignments, timestamp confidence, neutral/user-supplied names and manual corrections
stay in SQLite. Visual event features reuse local model/vector caches independently of duplicate
rules. No GPS, semantics or identity extraction was added. Derived-cache clearing preserves
manual event edits and removes automatic event snapshots. The event timeline has no remote data.


Phase 5 ranking uses only existing local features/vectors. It never downloads or computes
embeddings and does not learn from favorites. Recommendation scores/explanations are local
SQLite metadata. CSV/JSON downloads intentionally include local paths/names and user labels,
not original images. Users control exporting/sharing those manifests; there is no social sharing.


## Explicit preference learning (Phase 6)

Teach PhotoCull stores only explicit pair labels, source IDs/fingerprints, 15 feature scalars,
connected-group partitions, correction history and JSON model parameters/metrics. No photo copies,
full embedding vectors, facial identity or remote training are added. Preference data may reveal
taste; it stays in the private 0600 local SQLite database and is not sent to audit services or logs.
No encryption is provided. Reset My Learned Preferences removes the four preference tables'
contents and reclaims SQLite pages/WAL; originals, photo analysis, favorites and manual events remain.
Backups/SSD forensic erasure are not guaranteed. Ordinary derived-cache clearing preserves
preference data; unavailable/changed features invalidate its use until matching analysis exists.


## Web Demo (Phase 7)

Uploaded images are processed temporarily for this session and are not intentionally persisted
by PhotoCull. Uploads leave the browser and reach this server. This is not device-only processing.
The public entry is streamlit_app.py; the local folder entry is not a public deployment option.
There is no PhotoCull SQLite database, cache directory, temporary upload directory, permanent
thumbnail, embedding or preference storage. Only generated CC0 assets are bundled on disk.

Original buffers are decoded one at a time and not retained by DemoSession. Header dimensions
are checked before decoding (8 MP maximum); views are reduced to 2048 pixels, thumbnails to
512 pixels/256 KiB. EXIF extraction is limited to orientation/capture time/timezone, without GPS.
Scalar features, verification arrays, filenames, previews, decisions and preference state remain
in session RAM. The source abstraction has no dependency on Streamlit UploadedFile objects.

Clear temporary session releases those references. A registry bounds four sessions per process
and clears idle state after 15 minutes (30-second sweep); disconnected framework sessions have
a 120-second TTL. No persistent shared data cache holds uploads. Streamlit's native media and
upload manager and browser buffers have their own transient lifecycle; immediate forensic RAM
wiping or hosting-provider retention guarantees are not claimed. Process restart loses all state.

Operational failures show generic messages without file bytes, EXIF, filenames or preference
labels. PhotoCull adds no telemetry or remote inference. Framework/server infrastructure can
still record connection metadata. Never put the app behind hosting that intentionally archives
request bodies. Public hosting security/quotas remain an operator responsibility.

CSV/JSON web exports are explicitly downloaded metadata; paths are the placeholder
session-upload. Local exports deliberately include local paths. Neither edition moves, copies
or deletes originals. Derived cache clearing and preference reset are separate Local controls;
neither is secure erasure. Private preference labels/study artifacts must not be pushed publicly.
