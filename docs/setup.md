# Setup

Use Python 3.11+ and a virtual environment. See the README commands. Tested here with Python
3.13.6 on Apple Silicon/macOS; Linux is supported by the POSIX locking design but not validated
on this host. Windows is not yet supported because `fcntl` is required.

Dependencies: Pillow, NumPy, headless OpenCV and Streamlit. No GPU, model weights, external
database or inference credentials are needed. Pandas is a Streamlit dependency; analysis does
not require it. Do not install both GUI and headless OpenCV into the same environment.

Existing Phase 1 databases automatically migrate to schema 2. Restart Streamlit after upgrading
Python modules because a live process can retain stale imports. Keep the existing cache to
preserve decisions and scan history. Phase 2 added no runtime dependencies. Phase 3 optionally
installs PyTorch, torchvision, OpenCLIP and truststore; see [local model setup](embeddings.md).
Phase 4 optionally adds the events extra (scikit-learn/SciPy); time-only events need no
additional dependencies. The current database automatically upgrades to schema 6. No model is fetched at app startup. Phase 5 ranking adds no dependencies and never
computes embeddings; optional existing vector caches are reused.

Run Streamlit from the repository root so `.streamlit/config.toml` is loaded. Bind only to
127.0.0.1 and explicitly disable usage stats as shown in README. The app is intended for a
single trusted local user; it is not authenticated for network hosting.

The UI accepts a path on the machine running Python, not a browser file upload. Default cache:
`~/.photocull`. To keep data inside the project:

```sh
PHOTOCULL_CACHE_DIR=/absolute/project/.photocull .venv/bin/streamlit run src/photocull/ui/app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

Use `PHOTOCULL_CONFIG=/absolute/project/configs/default.toml` for UI measurement configuration.
CLI global options must precede the subcommand. Relative CLI cache paths are made absolute.
Source and cache directories must not overlap. Cache ancestors must not be symlinks; on macOS,
use `/private/tmp/...` rather than `/tmp/...` for explicitly selected temporary paths.

Initial installation and vulnerability checks require internet access to package services.
For an offline installation, prepare a compatible wheelhouse beforehand, then use pip's
`--no-index --find-links` options. PhotoCull does not fetch dependencies at application startup.


Phase 6 uses NumPy already installed; no neural training, downloads or additional dependency.
Restart Streamlit after updating. Set PHOTOCULL_WEB_DEMO=1 to force session-only preference
storage; this is a behavior design for future demos, not a deployed or authenticated service.

Phase 7 supersedes the preference-only demo flag: deploy streamlit_app.py for the
upload-only memory edition. Never deploy the local folder UI. See deployment.md.
