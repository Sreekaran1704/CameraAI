"""Bounded, memory-only Web Demo orchestration. No cache, SQLite, files or inference."""

import threading
import time
import uuid
import weakref

import cv2

from photocull.config import DuplicateConfig, EventConfig, QualityConfig, RankingConfig
from photocull.events import discover
from photocull.hashing import PerceptualHashService
from photocull.quality import QualityAnalyzer
from photocull.ranking import rank, shortlist
from photocull.similarity import PhotoFeatures, SimilarityEngine, verification_from_image
from photocull.sources import UploadedImageSource
from photocull.thumbnails import thumbnail_bytes

MAX_IMAGES = 30
MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_TOTAL_BYTES = 60 * 1024 * 1024
MAX_PIXELS = 8_000_000
DECODE_EDGE = 2048
THUMBNAIL_EDGE = 512
MAX_THUMBNAIL_BYTES = 256 * 1024
MAX_ATTEMPTS = 40
MAX_PREFERENCE_ACTIONS = 256
MAX_SESSIONS = 4
SESSION_TTL = 15 * 60
PROCESSING = threading.BoundedSemaphore(1)
cv2.setNumThreads(1)


class DemoLimitError(ValueError):
    pass


class DemoBusyError(ValueError):
    pass


class DemoSession:
    def __init__(self):
        self.token = uuid.uuid4().hex
        self.photos = []
        self.rows = {}
        self.thumbnails = {}
        self.decisions = {}
        self.preference_state = {}
        self.preference_actions = 0
        self.failures = []
        self.total_upload_bytes = 0
        self.attempts = 0
        self.closed = False
        self.timings = {
            "decode": 0.0,
            "quality": 0.0,
            "hashing": 0.0,
            "thumbnail": 0.0,
            "duplicates": 0.0,
            "events": 0.0,
            "ranking": 0.0,
            "total": 0.0,
        }
        self.duplicates = {"groups": [], "statistics": {}, "exact_reclaimable_bytes": 0}
        self.events = {"events": [], "assignments": {}, "event_count": 0, "unassigned_count": 0}
        self.ranking = {"ranked": [], "selected": []}
        self.lock = threading.RLock()

    def add(self, source):
        """One decoded image at a time; originals are never kept in the session object."""
        with self.lock:
            if self.closed:
                raise DemoLimitError("This session expired. Start a new temporary session.")
            if len(self.photos) >= MAX_IMAGES:
                raise DemoLimitError("This demo accepts at most 30 images per session.")
            if self.attempts >= MAX_ATTEMPTS:
                raise DemoLimitError("This session reached its attempt limit. Clear it to restart.")
            size = len(source.data)
            if not 0 < size <= MAX_FILE_BYTES:
                raise DemoLimitError("Each image must be nonempty and at most 15 MiB.")
            if self.total_upload_bytes + size > MAX_TOTAL_BYTES:
                raise DemoLimitError("The session upload budget is 60 MiB. Clear it to restart.")
            if not PROCESSING.acquire(blocking=False):
                raise DemoBusyError("The demo is processing another image. Try again shortly.")
            self.total_upload_bytes += size
            self.attempts += 1
            start = time.perf_counter()
            image = None
            try:
                stage = time.perf_counter()
                image, meta = source.read(MAX_PIXELS, DECODE_EDGE)
                self.timings["decode"] += time.perf_counter() - stage
                identifier = f"photo-{self.attempts:03d}"
                stage = time.perf_counter()
                quality = QualityAnalyzer(QualityConfig(analysis_edge=512)).analyze(
                    image, (meta["width"], meta["height"])
                )
                self.timings["quality"] += time.perf_counter() - stage
                stage = time.perf_counter()
                hashes = PerceptualHashService().analyze(image)
                verification = verification_from_image(image)
                self.timings["hashing"] += time.perf_counter() - stage
                stage = time.perf_counter()
                thumb, _, _ = thumbnail_bytes(image, THUMBNAIL_EDGE, 80)
                if len(thumb) > MAX_THUMBNAIL_BYTES:
                    thumb, _, _ = thumbnail_bytes(image, 384, 65)
                if len(thumb) > MAX_THUMBNAIL_BYTES:
                    raise DemoLimitError("Preview exceeds the bounded memory allowance.")
                self.timings["thumbnail"] += time.perf_counter() - stage
                photo = PhotoFeatures(
                    identifier,
                    meta["fingerprint"],
                    meta["content_sha256"],
                    meta["width"],
                    meta["height"],
                    size,
                    hashes,
                    quality,
                    meta["capture_time"],
                    meta["capture_timezone"],
                    None,
                    meta["filename"],
                    verification=verification,
                )
                self.photos.append(photo)
                self.thumbnails[identifier] = thumb
                self.rows[identifier] = {
                    "path": "session-upload",
                    "metadata": meta,
                    "id": identifier,
                }
                return identifier
            except MemoryError:
                self.failures.append("An image exceeded available memory. Try a smaller image.")
                return None
            except (ValueError, OSError, SyntaxError) as exc:
                # Never expose a filename, EXIF value, binary content or traceback in logs.
                message = (
                    str(exc)
                    if isinstance(exc, DemoLimitError)
                    else (
                        "An image could not be decoded safely. "
                        "Use JPEG/PNG/WEBP below 8 megapixels."
                    )
                )
                self.failures.append(message)
                return None
            finally:
                if image is not None:
                    image.close()
                self.timings["total"] += time.perf_counter() - start
                PROCESSING.release()

    def analyze(self, variant="B"):
        with self.lock:
            if self.closed:
                raise DemoLimitError("Session expired.")
            if not PROCESSING.acquire(blocking=False):
                raise DemoBusyError("The demo is busy. Try again shortly.")
            try:
                start = time.perf_counter()
                duplicates = SimilarityEngine(
                    DuplicateConfig(max_candidates_per_photo=29, max_comparisons=435)
                ).detect(self.photos)
                self.timings["duplicates"] = time.perf_counter() - start
                start = time.perf_counter()
                events = discover(self.photos, EventConfig())
                self.timings["events"] = time.perf_counter() - start
                start = time.perf_counter()
                config = RankingConfig(variant=variant)
                ranked = rank(self.photos, config)
                coverage = {
                    p.id: events["assignments"].get(p.id, {}).get("event_id") or "unassigned"
                    for p in self.photos
                }
                selected = shortlist(
                    self.photos,
                    ranked["ranked"],
                    min(20, len(self.photos)),
                    config,
                    groups=duplicates["groups"],
                    coverage=coverage,
                )
                self.duplicates, self.events = duplicates, events
                self.ranking = {**ranked, **selected}
                self.timings["ranking"] = time.perf_counter() - start
                return self.ranking
            finally:
                PROCESSING.release()

    def data(self):
        return {
            "photos": self.photos,
            "rows": self.rows,
            "groups": self.duplicates["groups"],
            "events": self.events,
            "decisions": self.decisions,
            "vectors": {},
        }

    def clear(self):
        with self.lock:
            self.photos.clear()
            self.rows.clear()
            self.thumbnails.clear()
            self.decisions.clear()
            self.preference_state.clear()
            self.failures.clear()
            self.duplicates = {"groups": [], "statistics": {}, "exact_reclaimable_bytes": 0}
            self.events = {"events": [], "assignments": {}}
            self.ranking = {"ranked": [], "selected": []}
            self.closed = True


class SessionRegistry:
    """Weak leases bound active sessions; TTL purge clears memory even with open browser tabs."""

    def __init__(self, maximum=MAX_SESSIONS, ttl=SESSION_TTL, clock=time.monotonic):
        self.maximum, self.ttl, self.clock = maximum, ttl, clock
        self.leases = {}
        self.lock = threading.RLock()

    def purge(self):
        with self.lock:
            now = self.clock()
            for token, (reference, touched) in list(self.leases.items()):
                session = reference()
                if session is None or now - touched >= self.ttl:
                    if session is not None:
                        session.clear()
                    del self.leases[token]

    def acquire(self, session=None):
        with self.lock:
            self.purge()
            if session and not session.closed and session.token in self.leases:
                self.leases[session.token] = (weakref.ref(session), self.clock())
                return session
            if len(self.leases) >= self.maximum:
                raise DemoBusyError("All four temporary demo slots are in use. Please try later.")
            session = DemoSession()
            self.leases[session.token] = (weakref.ref(session), self.clock())
            return session

    def release(self, session):
        with self.lock:
            session.clear()
            self.leases.pop(session.token, None)


REGISTRY = SessionRegistry()


def start_cleanup():
    """One daemon sweeper per interpreter. No disk logs, telemetry or session content."""
    with REGISTRY.lock:
        if getattr(REGISTRY, "sweeper", None) is not None:
            return

        def sweep():
            while True:
                time.sleep(30)
                REGISTRY.purge()

        REGISTRY.sweeper = threading.Thread(
            target=sweep, name="photocull-session-cleanup", daemon=True
        )
        REGISTRY.sweeper.start()


def add_sources(session, sources):
    """Small headless API for bundled fixtures/tests; same single-image services."""
    sources = list(sources)
    if len(sources) + len(session.photos) > MAX_IMAGES:
        raise DemoLimitError("This demo accepts at most 30 images per session.")
    if sum(len(s.data) for s in sources) + session.total_upload_bytes > MAX_TOTAL_BYTES:
        raise DemoLimitError("The session upload budget is 60 MiB.")
    for source in sources:
        if not isinstance(source, UploadedImageSource):
            raise ValueError("Only decoded upload sources are supported.")
        session.add(source)
    return session.analyze()
