import json
import subprocess
import sys
import time
from pathlib import Path

from photocull.cli import main
from photocull.fixtures import generate_fixtures
from photocull.jobs import recover_interrupted, start_job
from photocull.pipeline import analyze_run, run_sync
from photocull.scanner import content_hash
from photocull.storage import Repository


def test_fixture_generation_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    generate_fixtures(a)
    generate_fixtures(b)
    assert {p.name: content_hash(p) for p in a.iterdir()} == {
        p.name: content_hash(p) for p in b.iterdir()
    }


def test_cli_scan_analyze_status_clear(photos, config, capsys):
    for command in (
        ("scan", str(photos)),
        ("analyze", str(photos)),
        ("cache", "status"),
        ("cache", "clear"),
    ):
        assert main(["--cache-dir", str(config.cache_dir), *command]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data
    assert main(["--cache-dir", str(config.cache_dir), "scan", "/nonexistent-photocull"]) == 2
    assert json.loads(capsys.readouterr().err)["error"]


def test_scan_only_no_derived(photos, config):
    result = run_sync(photos, config, mode="scan")
    assert result["processed"] == 18 and result["analyzed"] == 0
    repo = Repository(config.cache_dir / "metadata.db")
    assert repo.counts()["quality_measurements"] == 0
    assert len(repo.failures(result["run_id"])) == 1
    repo.close()


def test_cancel_between_files_and_recovery(photos, config, monkeypatch):
    from photocull.quality import QualityAnalyzer

    actual = QualityAnalyzer.analyze

    def cancel_after_first(self, image):
        result = actual(self, image)
        repo = Repository(config.cache_dir / "metadata.db")
        repo.cancel(repo.runs()[0]["id"])
        repo.close()
        return result

    monkeypatch.setattr(QualityAnalyzer, "analyze", cancel_after_first)
    interrupted = run_sync(photos, config)
    repo = Repository(config.cache_dir / "metadata.db")
    assert repo.get_run(interrupted["run_id"])["status"] == "cancelled"
    assert interrupted["processed"] == 1 and interrupted["analyzed"] == 1
    assert len(repo.results(interrupted["run_id"])) == 1
    monkeypatch.setattr(QualityAnalyzer, "analyze", actual)
    resumed = run_sync(photos, config)
    assert resumed["cache_hits"] == 1 and resumed["analyzed"] == 17
    repo.close()


def test_background_job_persists_progress(photos, config):
    run_id = start_job(photos, config)
    repo = Repository(config.cache_dir / "metadata.db")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        run = repo.get_run(run_id)
        if run["status"] in {"completed", "failed"}:
            break
        time.sleep(0.05)
    assert run["status"] == "completed"
    assert json.loads(run["progress_json"])["analyzed"] == 17
    assert len(repo.results(run_id)) == 17
    repo.close()


def test_dead_worker_recovery(photos, config):
    run_sync(photos, config)
    repo = Repository(config.cache_dir / "metadata.db")
    run_id = repo.create_run(photos, "analyze", config.snapshot())
    with repo.db:
        repo.db.execute(
            "UPDATE scan_runs SET status='running', worker_pid=99999999 WHERE id=?", (run_id,)
        )
    recover_interrupted(repo)
    assert repo.get_run(run_id)["status"] == "interrupted"
    result = analyze_run(config, run_id)
    assert result["cache_hits"] == 17
    repo.close()


def test_network_denied_in_subprocess(photos, config, tmp_path):
    # Network interdiction applies inside an actual CLI child, not only pytest's process.
    (tmp_path / "sitecustomize.py").write_text(
        "import socket\n"
        "def deny(*a, **kw): raise RuntimeError('NETWORK FORBIDDEN')\n"
        "socket.socket.connect=deny\nsocket.socket.connect_ex=deny\n"
        "socket.create_connection=deny\n"
    )
    import os

    env = {**os.environ, "PYTHONPATH": str(tmp_path) + os.pathsep + str(Path("src").resolve())}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "photocull.cli",
            "--cache-dir",
            str(config.cache_dir),
            "analyze",
            str(photos),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["analyzed"] == 17
    assert "NETWORK FORBIDDEN" not in result.stderr


def test_streamlit_pages_app_smoke(photos, config, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("PHOTOCULL_CACHE_DIR", str(config.cache_dir))
    run_sync(photos, config)
    app = AppTest.from_file(Path("src/photocull/ui/app.py").resolve(), default_timeout=15).run()
    assert not app.exception
    app.sidebar.radio[0].set_value("Overview").run()
    assert not app.exception
    assert app.metric[4].value == "17"
    app.sidebar.radio[0].set_value("Cache").run()
    assert not app.exception


def test_source_changes_during_analysis_isolated(photos, config, monkeypatch):
    from photocull.quality import QualityAnalyzer

    actual = QualityAnalyzer.analyze
    changed = False

    def change_once(self, image):
        nonlocal changed
        result = actual(self, image)
        if not changed:
            changed = True
            # First sorted readable file is blurred.png.
            with (photos / "blurred.png").open("ab") as stream:
                stream.write(b"changed-during-analysis")
        return result

    monkeypatch.setattr(QualityAnalyzer, "analyze", change_once)
    result = run_sync(photos, config)
    assert result["failures"] == 2 and result["analyzed"] == 16
    repo = Repository(config.cache_dir / "metadata.db")
    assert any(f["error_type"] == "SourceChangedError" for f in repo.failures(result["run_id"]))
    repo.close()
