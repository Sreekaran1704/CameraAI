"""Internal worker entry point. Configuration is read from the persisted run."""

import json
import logging
import sys
from pathlib import Path

from photocull.cache import Cache
from photocull.config import Config
from photocull.pipeline import analyze_run
from photocull.storage import Repository


def main():
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    cache = Cache(Path(sys.argv[1]))
    repo = Repository(cache.root / "metadata.db")
    try:
        config = Config.from_snapshot(json.loads(repo.get_run(sys.argv[2])["config_json"]))
    finally:
        repo.close()
    analyze_run(config, sys.argv[2], thorough="--thorough" in sys.argv[3:])


if __name__ == "__main__":
    main()
