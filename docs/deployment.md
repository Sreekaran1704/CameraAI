# PhotoCull Web Demo deployment

Status: prepared and verified on localhost, **not deployed**. This workspace has no Git
repository; Phase 7 did not initialize one, stage, commit, push, create an account or deploy.

## Publish the correct edition

Deploy **streamlit_app.py**, never src/photocull/ui/app.py. The root entry bootstraps src/
and opens only the upload workflow. Its runtime does not instantiate Cache or Repository.
Root requirements.txt pins the tested four direct public runtime dependencies. Optional
Torch/OpenCLIP/scikit-learn and development tools are excluded. No API secrets are required.

Use **Python 3.13** in Community Cloud Advanced settings (locally tested with 3.13.6).
Cloud installs on Linux; local macOS timings do not establish Cloud performance.
Cloud reads dependencies from the entry directory or repository root; root requirements.txt
takes precedence over pyproject.toml in this layout. See the official
[dependency guide](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies).
The shared config retains CORS/XSRF protections, disables telemetry/static serving/error
details, sets 15 MiB native uploads and 20 MiB messages. It leaves the bind address to
the hosting platform; local commands explicitly bind loopback.

## Exact operator steps

1. Create an empty GitHub repository named PhotoCull under your account; do not add files
   through GitHub's initialization form. Replace YOUR-USER below. Before publishing, review
   source/docs/test fixtures and exclude private labels, exports, caches, logs and model weights.
   .gitignore excludes .photocull/, benchmark-output/, .venv/, secrets, databases and checkpoints.
2. From the project root, **run these commands yourself when ready**. These are instructions,
   not actions performed by Phase 7. The explicit file list avoids publishing old screenshots
   or private evaluation outputs.

   ```sh
   git init -b main
   git add .gitignore .streamlit/config.toml pyproject.toml requirements.txt streamlit_app.py README.md
   git add src tests assets docs
   git add benchmarks/generate_public_demo.py benchmarks/phase7_benchmark.py benchmarks/summarize_verified.py
   git add benchmarks/phase7-performance.json benchmarks/verified-results.json
   git add benchmarks/phase7_startup.py benchmarks/phase7-startup.json benchmarks/phase7-validation.json
   git add benchmarks/phase7-environment.txt benchmarks/phase7-dependency-audit.json
   git diff --cached --stat
   git diff --cached
   git commit -m "Prepare PhotoCull local edition and bounded web demo"
   git remote add origin https://github.com/YOUR-USER/PhotoCull.git
   git push -u origin main
   ```

   Preserve the original generated evaluation JSONs privately. If publishing their full
   provenance, separately review and add the five source JSON files listed in
   benchmarks/verified-results.json; the curated summary already contains the relevant metrics.
3. Sign in to [Streamlit Community Cloud](https://share.streamlit.io/), connect GitHub,
   choose Create app, and deploy an existing app. Select repository YOUR-USER/PhotoCull,
   branch main, main file **streamlit_app.py**. Choose Python 3.13 in Advanced settings.
   Leave Secrets empty. Choose an available custom subdomain, e.g. photocull-yourname.
4. Click Deploy and wait for the build. Expected custom URL:
   https://photocull-yourname.streamlit.app/ (availability is not promised). Without a chosen
   subdomain Cloud supplies a generated *.streamlit.app URL.
   These steps follow the official [deployment guide](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy).
5. Open the public URL in a fresh browser. Confirm the Web Demo label and temporary-server
   privacy sentence; there must be no folder scanner or SQLite cache UI.
6. Run Try Demo Without Uploading Photos: 12 generated images should show 1 exact, 2 near,
   3 burst groups and 3 events. Check Review, Events, Best Photos, Preferences and CSV/JSON.
7. Test with disposable generated images: one valid JPEG/PNG/WEBP, a corrupt file, a >15 MiB
   file, an >8 MP image and the 30-image limit. At 30 the uploader must disable; cumulative
   accepted attempts consume a 60 MiB budget. Clear must return to an empty session.
   Confirm a second browser session cannot see the first one's images or preferences.
   Leave a session idle >15 minutes and verify expiry; sweep cadence is 30 seconds.
8. Embed the public URL using the portfolio snippet and verify at desktop and phone widths.
   Test uploads/downloads in the iframe and Open Full Demo. Do not disable CORS/XSRF.
9. Inspect Cloud logs for startup/operational failures without collecting photo contents,
   EXIF, user labels or filenames. Recheck package advisories and actual Cloud memory/load
   before promoting the demo widely. Configure platform quotas if available.

## Operations and limits

The app admits four sessions per process, one analysis worker and one cleanup thread.
It returns a busy message rather than queueing unbounded work. Public embedding inference
is disabled (batch size zero), comparisons cap at 435 for 30 images. Explicit Clear and
15-minute idle expiry release PhotoCull references; disconnected Streamlit sessions expire
after 120 seconds. A process restart drops every session. No temporary upload directories
are created. Streamlit owns transient uploaded-file/media buffers and the browser has its
own copies; this is logical cleanup, not a secure erase or a promise about host infrastructure.

These controls bound admitted application work, not arbitrary malicious connections or
hosting-platform buffers. A free shared host can still become unavailable. Four concurrent
sessions, Linux installation and remote iframe behavior must be verified after deployment;
localhost tests are not a public load test. Personalization validation is optional and does
not block deployment; C remains experimental and guarded.
