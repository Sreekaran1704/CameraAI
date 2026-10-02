"""JSON CLI: stdout is results; errors/logs go to stderr."""

import argparse
import json
import logging
import sys
from pathlib import Path

from photocull.cache import Cache
from photocull.config import load_config
from photocull.pipeline import run_sync
from photocull.storage import Repository


def main(argv=None):
    parser = argparse.ArgumentParser(prog="photocull")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--cache-dir", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("scan", "analyze"):
        sub = commands.add_parser(command)
        sub.add_argument("folder", type=Path)
        sub.add_argument(
            "--thorough",
            action="store_true",
            help="Rehash/recompute even if fast fingerprints match",
        )
    cache_parser = commands.add_parser("cache")
    cache_parser.add_argument("action", choices=("status", "clear"))
    fixtures_parser = commands.add_parser("fixtures")
    fixtures_parser.add_argument("folder", type=Path)
    fixtures_parser.add_argument("--extra", type=int, default=0)
    bench_parser = commands.add_parser("benchmark")
    bench_parser.add_argument("--extra", type=int, default=100)
    duplicate_parser = commands.add_parser("duplicates")
    duplicate_parser.add_argument("folder", type=Path)
    duplicate_parser.add_argument("--thorough", action="store_true")
    evaluation_parser = commands.add_parser("evaluate-duplicates")
    evaluation_parser.add_argument("--manifest", type=Path)
    evaluation_parser.add_argument("--format", choices=("json", "csv"), default="json")
    fixture_duplicates = commands.add_parser("duplicate-fixtures")
    fixture_duplicates.add_argument("folder", type=Path)
    commands.add_parser("benchmark-duplicates")
    setup = commands.add_parser("model-setup")
    setup.add_argument("model", choices=("mobilenet", "tinyclip"))
    hybrid = commands.add_parser("evaluate-hybrid")
    hybrid.add_argument("--manifest", type=Path, required=True)
    hybrid.add_argument("--hard-manifest", type=Path)
    embedding_bench = commands.add_parser("benchmark-embeddings")
    embedding_bench.add_argument("--evaluation", type=Path, required=True)
    hard = commands.add_parser("hard-duplicate-fixtures")
    hard.add_argument("--manifest", type=Path, required=True)
    hard.add_argument("folder", type=Path)
    event_fixture = commands.add_parser("event-fixtures")
    event_fixture.add_argument("folder", type=Path)
    event_eval = commands.add_parser("evaluate-events")
    event_eval.add_argument("--manifest", type=Path, required=True)
    commands.add_parser("benchmark-events")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    try:
        config = load_config(args.config, args.cache_dir)
        if args.command in {"scan", "analyze", "duplicates"}:
            mode = "analyze" if args.command == "duplicates" else args.command
            result = run_sync(args.folder.expanduser(), config, mode, args.thorough)
            cache = Cache(config.cache_dir)
            repo = Repository(cache.root / "metadata.db")
            try:
                result["status"] = repo.get_run(result["run_id"])["status"]
                if args.command == "duplicates":
                    from photocull.duplicate_storage import DuplicateStore

                    result["detection"] = DuplicateStore(repo).for_scan(result["run_id"])
            finally:
                repo.close()
        elif args.command == "event-fixtures":
            from photocull.event_evaluation import generate_events

            manifest = generate_events(args.folder)
            result = {
                "manifest": str((args.folder / "manifest.json").absolute()),
                "photos": len(manifest["photos"]),
            }
        elif args.command == "evaluate-events":
            from photocull.event_evaluation import evaluate_events

            result = evaluate_events(args.manifest, config.cache_dir)
        elif args.command == "benchmark-events":
            from photocull.event_evaluation import benchmark_metadata

            result = {"metadata_benchmarks": benchmark_metadata()}
        elif args.command == "hard-duplicate-fixtures":
            from photocull.hybrid_evaluation import expand_hard_dataset

            result = {"manifest": str(expand_hard_dataset(args.manifest, args.folder).absolute())}
        elif args.command == "benchmark-embeddings":
            from photocull.embedding_benchmark import benchmark_embeddings

            result = benchmark_embeddings(config.cache_dir.absolute(), args.evaluation)
        elif args.command == "evaluate-hybrid":
            from photocull.hybrid_evaluation import evaluate_hybrid

            result = evaluate_hybrid(args.manifest, config.cache_dir, args.hard_manifest)
        elif args.command == "model-setup":
            from photocull.embeddings import setup_model

            result = setup_model(Cache(config.cache_dir), args.model)
        elif args.command == "evaluate-duplicates":
            from photocull.duplicate_evaluation import evaluate_duplicates, evaluation_csv

            result = evaluate_duplicates(args.manifest, config.duplicates)
            if args.format == "csv":
                print(evaluation_csv(result), end="")
                return 0
        elif args.command == "duplicate-fixtures":
            from photocull.duplicate_evaluation import generate_duplicate_dataset

            generated = generate_duplicate_dataset(args.folder)
            result = {
                "manifest": str((args.folder / "manifest.json").absolute()),
                "dataset_version": generated["dataset_version"],
            }
        elif args.command == "benchmark-duplicates":
            from photocull.duplicate_benchmark import benchmark_duplicates

            result = benchmark_duplicates()
        elif args.command == "fixtures":
            from photocull.fixtures import generate_fixtures

            result = generate_fixtures(args.folder, args.extra)
        elif args.command == "benchmark":
            from photocull.benchmark import benchmark

            result = benchmark(args.extra)
        else:
            cache = Cache(config.cache_dir)
            repo = Repository(cache.root / "metadata.db")
            try:
                if args.action == "clear":
                    cache.clear_derived(repo)
                result = {**cache.status(), "records": repo.counts()}
            finally:
                repo.close()
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 1 if result.get("status") == "failed" else 0
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
