"""Application-owned cache with conservative cleanup boundaries."""

import json
import os
import re
import shutil
from contextlib import contextmanager
from pathlib import Path

MARKER = {"application": "photocull", "layout_version": 1}
DERIVED_DIRS = ("thumbnails", "embeddings")


def refuse_symlinks(path: Path) -> Path:
    path = Path(os.path.abspath(path.expanduser()))
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError("Symlinked application paths are not allowed")
    return path


class Cache:
    def __init__(self, root: Path):
        self.root = refuse_symlinks(root)
        if self.root == Path.home() or self.root == Path(self.root.anchor):
            raise ValueError("Cache must use a dedicated application directory")
        marker = self.root / ".photocull-cache.json"
        if self.root.exists() and any(self.root.iterdir()) and not marker.is_file():
            raise ValueError("Refusing a nonempty directory without a PhotoCull marker")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if marker.exists():
            refuse_symlinks(marker)
            if json.loads(marker.read_text()) != MARKER:
                raise ValueError("Unrecognized cache marker")
        else:
            marker.write_text(json.dumps(MARKER))
            marker.chmod(0o600)
        for name in (*DERIVED_DIRS, "models", "jobs", "logs"):
            directory = refuse_symlinks(self.root / name)
            directory.mkdir(exist_ok=True, mode=0o700)
        for name in ("metadata.db", "metadata.db-wal", "metadata.db-shm", "cache.lock"):
            refuse_symlinks(self.root / name)

    def assert_source(self, folder: Path):
        folder = refuse_symlinks(folder)
        if not folder.is_dir():
            raise ValueError("Source must be a readable directory")
        if (
            folder == self.root
            or folder.is_relative_to(self.root)
            or self.root.is_relative_to(folder)
        ):
            raise ValueError("Source and cache directories must not overlap")

    @contextmanager
    def lock(self):
        # Local desktop POSIX file lock also protects against concurrent CLI/UI cleanup.
        import fcntl

        target = refuse_symlinks(self.root / "cache.lock")
        with target.open("a") as stream:
            target.chmod(0o600)
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("PhotoCull cache is busy with another job") from exc
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def validate_cleanup(self):
        refuse_symlinks(self.root)
        marker = refuse_symlinks(self.root / ".photocull-cache.json")
        if json.loads(marker.read_text()) != MARKER:
            raise ValueError("Unrecognized cache marker")
        for name in DERIVED_DIRS:
            directory = refuse_symlinks(self.root / name)
            for path in directory.rglob("*"):
                if path.is_symlink():
                    raise ValueError("Refusing cleanup containing a symlink")
                if path.is_file() and not (
                    re.fullmatch(r"[0-9a-f]{64}\.(jpg|npy)", path.name)
                    or re.fullmatch(r"tmp[a-z0-9_]+\.tmp", path.name)
                ):
                    raise ValueError("Unexpected file in derived cache; cleanup refused")

    def clear_derived(self, repository):
        with self.lock():
            self.validate_cleanup()
            for row in repository.db.execute("SELECT path FROM source_photos"):
                source = Path(row[0]).resolve()
                if source == self.root or source.is_relative_to(self.root):
                    raise ValueError("Cleanup refused: registered source lies inside cache")
            repository.clear_derived()
            for name in DERIVED_DIRS:
                shutil.rmtree(self.root / name)
                (self.root / name).mkdir(mode=0o700)

    def status(self) -> dict:
        sizes = {}
        for name in DERIVED_DIRS:
            sizes[name] = sum(
                p.stat().st_size
                for p in (self.root / name).rglob("*")
                if p.is_file() and not p.is_symlink()
            )
        total = sum(
            p.stat().st_size for p in self.root.rglob("*") if p.is_file() and not p.is_symlink()
        )
        return {"root": str(self.root), "derived_bytes": sizes, "total_bytes": total}
