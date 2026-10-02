"""Subprocess workers persist progress in SQLite, surviving UI reruns/restarts."""

import json
import os
import subprocess
import sys
from pathlib import Path

from photocull.cache import Cache, refuse_symlinks
from photocull.config import Config
from photocull.storage import Repository, now


def start_job(root: Path, config: Config, thorough=False) -> str:
    cache = Cache(config.cache_dir)
    cache.assert_source(root)
    repo = Repository(cache.root / "metadata.db")
    try:
        with cache.lock():
            run_id = repo.create_run(root, "analyze", config.snapshot())
        # Use a module command and argument list, never a shell or source path interpolation.
        command = [sys.executable, "-m", "photocull.worker", str(cache.root), run_id]
        if thorough:
            command.append("--thorough")
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        log_path = refuse_symlinks(cache.root / "logs" / "worker.log")
        with log_path.open("ab") as log:
            log_path.chmod(0o600)
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                env=environment,
                start_new_session=True,
            )
        with repo.db:
            repo.db.execute("UPDATE scan_runs SET worker_pid=? WHERE id=?", (process.pid, run_id))
        return run_id
    finally:
        repo.close()


def recover_interrupted(repo: Repository):
    """Mark dead workers; a fresh analysis run recovers completed component results."""
    for run in repo.runs():
        if run["status"] not in {"running", "queued"} or not run["worker_pid"]:
            continue
        try:
            os.kill(run["worker_pid"], 0)
        except ProcessLookupError:
            with repo.db:
                repo.db.execute(
                    "UPDATE scan_runs SET status='interrupted',finished_at=? WHERE id=?",
                    (now(), run["id"]),
                )
        except PermissionError:
            pass


def job_snapshot(config: Config, run_id: str):
    cache = Cache(config.cache_dir)
    repo = Repository(cache.root / "metadata.db")
    try:
        recover_interrupted(repo)
        run = repo.get_run(run_id)
        run["progress"] = json.loads(run["progress_json"])
        return run
    finally:
        repo.close()
