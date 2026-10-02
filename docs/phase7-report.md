# PhotoCull Phase 7 completion report

Historical initial Phase 7 snapshot: measurements and demo counts below used public_demo_v1.
The current photographic public_demo_v2 is documented in demo-dataset.md.

Release: 0.7.0. Phase 7 only. No Git initialization, staging, commit, push, account creation or
deployment occurred. The original frozen A/B/duplicate/event rules remain unchanged.

## 1. Final architecture

FileImageSource and UploadedImageSource share decoded RGB images and whitelisted metadata.
Quality, perceptual hashes, local pixel verification, thumbnail encoding, duplicate grouping,
time events, ranking, explanations and metadata exports are shared services. CV contains no
Streamlit upload types. Local pipeline owns disk/SQLite orchestration; DemoSession owns only RAM.
The two UI entry points share style.py, not storage lifecycles.

## 2. Local Edition behavior

Folders, private SQLite schema 6, versioned derived cache, decisions, manual event corrections
and guarded persistent preferences remain available. Sources are read-only. Default quality and
hash rules are preserved, including source-change detection and EXIF orientation. Larger
collections work incrementally; workers are cancellable and cache protected by POSIX locks.

## 3. Web Demo behavior

Explicit browser uploads only; sequential single-image input bounds native upload buffering.
No server folder chooser, Repository, Cache, permanent preferences or model inference.
Overview → Review → Events → Best Photos → Preferences → Export renders only the active view.
Generated demo or uploads use the same memory session. Refresh retries analysis atomically:
failed result processing leaves prior results and valid photos available.

## 4. Privacy differences

Local: photos remain on the device; derived metadata/previews/preferences persist in a private
cache (not encrypted by PhotoCull). Web: **Uploaded images are processed temporarily for this
session and are not intentionally persisted by PhotoCull.** Images reach the server.
No remote inference, accounts or telemetry were added. EXIF extraction is limited to orientation
and capture time/timezone; GPS is omitted. Logical cleanup cannot promise forensic erasure,
browser/framework buffer removal or hosting-provider retention policy. See privacy.md.

## 5. Deployment entry point

Deploy root **streamlit_app.py** with root **requirements.txt**, Python **3.13**.
Four tested direct runtime pins: Pillow 12.3.0, NumPy 2.5.3, OpenCV-headless 4.14.0.94,
Streamlit 1.64.0. No optional ML or dev tools/secrets in the public dependency file.
Cloud/Linux installation and actual host capacity are pending deployment, not claimed tested.

## 6. Upload/resource limits

| Resource | Web cap |
|---|---|
| Images | 30 valid images/session |
| Per upload | 15 MiB, JPEG/PNG/WEBP only |
| Total upload budget | 60 MiB/session including failed decode attempts |
| Attempts | 40/session |
| Header pixel count | 8,000,000 before pixel allocation |
| Decoded view | 2048-pixel maximum edge |
| Thumbnail | 512-pixel edge and 256 KiB maximum |
| Pairwise verification | 435 comparisons; 29 candidate neighbors |
| Processing | 1 shared analysis worker; OpenCV 1 thread |
| Admission | 4 PhotoCull sessions/process |
| Embedding batch | 0; public inference disabled |
| Preference activity | 256 save/undo actions until preference reset |
| Idle cleanup | 15 minutes, checked every 30 seconds |
| Disconnected framework TTL | 120 seconds |

These bound admitted application work; hostile connections and platform buffers still require
hosting quotas. A public free host can become busy; bounded admission returns useful messages.

## 7. Styling/UI work

Shared deep teal/mint theme, serif hero, consistent type scale, spacing, rounded metric cards,
image grids, explanation expanders, native buttons and choices. Clear landing CTAs and edition
cards; generated hero, no remote image/fonts or animation. Result metrics separate exact, near,
burst and events; exact storage is an estimate and no deletion action exists. Cards distinguish
technical strengths/weaknesses from subjective/emotional value.

## 8. Embed-mode behavior

Use **?embed=true&compact=true**. Streamlit's supported embed parameter handles its chrome;
PhotoCull's compact flag hides repeated branding/mode cards/footer and reduces margins while
retaining privacy/upload/results. embed is reserved and unavailable through st.query_params.
A local portfolio iframe rendered the compact app; browser automation could not click its nested
controls. Direct demo/upload workflows were verified separately. At the actual 662-pixel browser
width, document width equaled viewport width (no page overflow). A requested 390-pixel override
was not applied by this browser; phone-width behavior and remote iframe interaction remain
operator checks. No CORS/XSRF protections were disabled. See portfolio-embed.md.

## 9. Bundled demo behavior

12 deterministic 640×400 generated illustrations, CC0-1.0, seed 170407; no personal photos.
**Try Demo Without Uploading Photos** produces 1 exact, 2 near and 3 burst groups, 3 time events,
a diverse explained shortlist and technical warnings. Groups can overlap across relation types.
Eight recommendations are returned rather than forced fillers. Browser upload of the generated
09-low-light.jpg increased 12 → 13 photos and reset the native file input.

## 10. Performance results

Fresh child process per size, one trial on macOS 27 ARM64/Python 3.13.6. All fixtures were generated
640×400 JPEGs cycling 12 scenes; metadata-only rows cycle scalar/hash features from those scenes.
Python socket connections were denied during core benchmarks. Timings are not estimates for
full-resolution RAW/HEIC, human camera rolls, public Cloud or simultaneous users. Imports are
timed separately; core timings exclude network, rendering and browser upload time.

| Edition / size | Imports s | Cold s | Warm s | Peak RSS MiB | Thumbnails MiB | Cache MiB |
|---|---:|---:|---:|---:|---:|---:|
| local / 100 | 0.086 | 1.348 | 0.065 | 94.2 | 1.310 | 2.263 |
| local / 500 | 0.086 | 6.584 | 0.278 | 124.6 | 6.532 | 10.258 |
| local / 1000 | 0.087 | 13.305 | 0.542 | 166.2 | 13.061 | 20.268 |
| web / 10 | 0.186 | 0.121 | 0.001 | 98.8 | 0.106 | 0.000 |
| web / 20 | 0.183 | 0.224 | 0.001 | 99.1 | 0.219 | 0.000 |
| web / 30 | 0.183 | 0.332 | 0.001 | 99.4 | 0.329 | 0.000 |

Cold stage measurements (seconds):

| Edition / size | Scan/decode s | Quality s | Hash s | Thumbnails s | Duplicates s | Events s | Ranking s |
|---|---:|---:|---:|---:|---:|---:|---:|
| local / 100 | 0.1386 | 0.7315 | 0.0621 | 0.2410 | 0.1116 | 0.0160 | 0.0120 |
| local / 500 | 0.6449 | 3.6896 | 0.2664 | 1.1836 | 0.5495 | 0.0726 | 0.0567 |
| local / 1000 | 1.2835 | 7.4937 | 0.5354 | 2.3803 | 1.1100 | 0.1497 | 0.1169 |
| web / 10 | 0.0148 | 0.0712 | 0.0142 | 0.0199 | 0.0005 | 0.0002 | 0.0003 |
| web / 20 | 0.0195 | 0.1361 | 0.0279 | 0.0393 | 0.0006 | 0.0003 | 0.0006 |
| web / 30 | 0.0251 | 0.2038 | 0.0419 | 0.0594 | 0.0007 | 0.0003 | 0.0007 |

5,000 metadata records: duplicate detection 2.139s,
events 0.033s, ranking/selection 0.142s,
peak RSS 248.4 MiB. Detection hit its 100,000 expensive-comparison budget
(1,132,503 candidate pairs), so this bounded run is not exhaustive.
No 5,000-image decoding/inference claim.
Local warm image-feature cache hit rate was 100%; web warm analysis reused all decoded features.
All generated original file hashes stayed unchanged. Embeddings were disabled, so timing is
null/inapplicable rather than an invented zero inference benchmark. Existing Phase 4 image
performance includes prior real MobileNet/TinyCLIP CPU inference at 100/500/1000 images; those
are historical optional-model measurements, not rerun in Phase 7.

Fresh Streamlit process reached loopback HTTP health 200 in **0.383s** (50 ms polling).
This is listener startup; lazy first-session imports/HTTP rendering are separate. Evidence:
phase7-startup.json and phase7-performance.json. Peak RSS is process high-water memory, not a
per-stage allocation trace or the deployed server's concurrent media-buffer footprint.

## 11. Graceful degradation

Hash-only duplicates, time-only events and generic A/B ranking work without optional models.
Local feature status shows checkpoint presence/checksum without importing Torch or downloading.
Optional setup remains explicit:

```sh
.venv/bin/python -m pip install -e '.[embeddings,events]'
.venv/bin/photocull --cache-dir .photocull model-setup mobilenet
.venv/bin/photocull --cache-dir .photocull model-setup tinyclip
```

Setup verifies pinned SHA-256; inference rechecks model identity/checksum. Installed weights
do not guarantee an optional runtime is installed. Public mode never performs model setup.
Corruption, unsupported/pixel/byte limits, low memory and busy worker errors preserve other photos.

## 12. Export/cache behavior

CSV/JSON manifest downloads contain metadata, explanations and explicit decisions; no copying,
moving, overwriting or deletion. Web uses session-upload path placeholders and exports the
currently viewed shortlist (A/B/C and selected size). Local manifests intentionally contain
local paths. Cache page separates total/derived storage, Clear Derived Cache and preference
reset. Derived clearing preserves preferences/decisions/manual edits/models; preference reset
preserves analysis/favorites/originals. Full destructive reset was not added. Web offers only
Clear temporary session; no temporary upload directories exist.

## 13. All validation results

**155 tests passed**, including the 142 previous tests and 13 Web Demo tests. All tests deny
outbound Python sockets. Coverage includes shared decode/orientation, pixel/view limits,
per-file/total/count/attempt limits, one-file isolation, worker release on memory failure,
atomic result failure, no Repository/disk writes/raw byte retention, separate sessions,
weakref/TTL cleanup, generated relation/event/ranking explanations, every web view, export
controls, compact startup, preference budget/reset and missing-model fallback.
Existing local CLI/UI, cancellation, migrations, corrections, cache safety and offline checks pass.

Real browser: local startup, Web landing, bundled workflow, explained shortlist, generated file
upload (13 photos), input reset and compact iframe rendering. AppTest checks all result views and
explicit session cleanup. Actual iframe interaction/phone override limits are described above.
Ruff lint/format checks and compilation pass. pip check passes. Dependency audit queried public
advisories for **87 installed packages**, **0 known vulnerabilities**; this is a point-in-time
advisory check, not proof of security. Audit does not send photo/label data.
Evidence is saved in phase7-validation.json and phase7-dependency-audit.json.

## 14. Deployment readiness

Upload-only entry, minimal dependency pins, safe config, generated assets and operator docs are
ready for review and a free Community Cloud trial. No paid API or secret is needed. A public
URL, Cloud install, platform resource quotas and remote iframe behavior are not yet verified.
Human preference validation is optional and does not block the demo; C stays experimental and
inactive without its own evidence guard.

## 15. Exact GitHub/Streamlit deployment steps

See deployment.md for the runnable manual GitHub initialization/staging/push commands and exact
Cloud repository/main/streamlit_app.py/Python 3.13 settings. The public URL will be
https://YOUR-APP.streamlit.app/ or Cloud's generated subdomain. The guide covers public privacy,
valid/oversize/corrupt uploads, demo/group checks, session isolation, cleanup and iframe smoke.
No Git or deployment actions were performed during this task.

## 16. Exact local launch commands

From /Users/sreekaran1704/Documents/CameraAI:

```sh
PHOTOCULL_CACHE_DIR=/Users/sreekaran1704/Documents/CameraAI/.photocull .venv/bin/streamlit run src/photocull/ui/app.py --server.address 127.0.0.1 --server.port 8517 --browser.gatherUsageStats false --server.headless true
.venv/bin/streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port 8518 --browser.gatherUsageStats false --server.headless true
```

Local: http://127.0.0.1:8517/ · Web preview: http://127.0.0.1:8518/
A clean web environment installs requirements.txt; Local Edition uses pip install -e '.[dev,events]'.
Reproduce core measurements with .venv/bin/python benchmarks/phase7_benchmark.py.
Temporary benchmark image/cache folders are cleaned by TemporaryDirectory.

## 17. Remaining limitations

Generated-fixture accuracy is not real-world/human accuracy. Web uses 512-pixel quality analysis
versus the Local default 1024 and no learned embeddings; Local evaluation metrics should not be
recast as newly evaluated Web accuracy. JPEG/PNG/WEBP only; EXIF-free uploads stay unassigned
instead of inventing capture times. Original files are not retained or exported by the Web Demo.
Fixed technical ranking can prefer noisy or emotionally weaker photos. Sessions are ephemeral;
no authentication/recovery or cross-process session store exists. Free-host concurrency/abuse,
Linux deployment, remote iframe interaction and phone-width behavior need post-deploy checks.
Cleanup is logical, not forensic. Local POSIX locks target macOS/Linux. Dependency advisories
change; repeat audits after installation/upgrades. Some decorative CSS uses Streamlit test IDs.
No Phase 8/new ML, face recognition, cloud inference, accounts, billing, social sharing or deletion.

## 18. Resume-ready verified metrics

Machine-readable benchmarks/verified-results.json preserves source/version/synthetic provenance:
near pair precision **98.36%**, recall **71.43%**, F1 **82.76%**; exact fixture pairs 100%;
hard hash holdout 1 false positive/79 negatives; hybrid MobileNet/TinyCLIP precision
95.91%/96.05% failed the expanded acceptance gate. Time-only events ARI .8743, NMI .9671,
purity .9426, pair precision .8641/recall .8900/F1 .8768.
Ranking A/B NDCG .6213/.6198 with known redundancy 0; B did not win.
Human labels **0**, C inactive; simulated C pair accuracy .8898 versus A .6720/B .6747,
but favorite recall at 3 regressed (.7917 versus .8333). Performance and privacy scope are
explicit. See verified-results.md. The earlier proposed 96% precision/89% recall claim is
not a verified product-wide result.
