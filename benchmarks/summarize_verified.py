"""Extract verified metrics without image/label records or personal filesystem paths."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
B = ROOT / "benchmarks"


def read(name):
    return json.loads((B / name).read_text())


def main():
    duplicates = read("phase3-evaluation.json")
    events = read("phase4-event-evaluation.json")
    ranking = read("phase5-evaluation.json")
    simulated = read("phase6-simulated-evaluation.json")
    human = read("phase6-local-evaluation.json")
    event = next(f for f in events["finalists"] if f["model"] == "disabled")["test"]
    hard = {
        name: {
            "accepted": model["accepted"],
            **{
                key: model["hard_benchmark"]["results"]["held_out"][key]
                for key in ("baseline", "hybrid")
            },
        }
        for name, model in duplicates["models"].items()
    }
    summary = {
        "version": "verified-results-v1",
        "application_version": "0.7.0",
        "evaluation_kind": (
            "Generated fixtures and authored/simulated labels; no human accuracy claim"
        ),
        "duplicates": {
            "source": "benchmarks/phase3-evaluation.json",
            "dataset": duplicates["dataset_version"],
            "held_out": duplicates["baseline"]["held_out"]["metrics"],
            "hard_negatives": hard,
            "default": "Frozen hash-only; hybrid experiments failed expanded precision gate",
            "warning": "Pair classification and complete-link group recall differ",
        },
        "events": {
            "source": "benchmarks/phase4-event-evaluation.json",
            "dataset": events["dataset_version"],
            "held_out": {k: v for k, v in event.items() if isinstance(v, (int, float))},
            "default": events["selected_default"],
            "limitation": "Close occasions over-merge; missing/mixed clock evidence splits groups",
        },
        "ranking": {
            "source": "benchmarks/phase5-evaluation.json",
            "dataset": ranking["dataset_version"],
            "label_source": ranking["label_source"],
            "A": ranking["A"]["test"]["metrics"],
            "B": ranking["B"]["test"]["metrics"],
            "conclusion": "B did not improve held-out macro NDCG over A",
            "limitation": (
                "Synthetic noise can score well; technical quality is not emotional value"
            ),
        },
        "personalization": {
            "human_feedback_count": human["feedback_count"],
            "active": human["model"]["active"],
            "status": "experimental; no real-user validation",
            "activation": (
                "50 decisive train pairs/3 groups; 10 held-out pairs/2 groups; C exceeds A and B"
            ),
            "simulated_source": "benchmarks/phase6-simulated-evaluation.json",
            "simulated_pairwise": simulated["abc"]["rankings"],
            "simulated_graded": simulated["graded_ranking"],
            "limitation": "C improved simulated pair accuracy but reduced favorite recall at 3",
        },
        "performance": read("phase7-performance.json"),
        "server_startup": read("phase7-startup.json"),
        "privacy": {
            "local": ("Local folders/SQLite/cache; no remote inference; read-only originals"),
            "web": ("Uploads reach server; memory-only; no PhotoCull persistence or inference API"),
            "web_cleanup": (
                "Explicit clear, weak session leases and 15-minute idle expiry; 30-second sweep"
            ),
            "limits": (
                "30 images, 15 MiB/file, 60 MiB/session, 8 MP, one analysis worker, four sessions"
            ),
            "limitation": (
                "Browser/framework/host buffers and forensic erasure are outside this guarantee"
            ),
        },
    }
    (B / "verified-results.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
