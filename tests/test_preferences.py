"""Offline Phase 6 learning, leakage, corrections, persistence and UI contracts."""

import json
from pathlib import Path

import numpy as np
import pytest
from test_ranking import photo

from photocull.config import Config
from photocull.pipeline import run_sync
from photocull.preference_evaluation import graded_metrics, learning_curve
from photocull.preference_storage import PreferenceStore, consistency
from photocull.preferences import (
    MINIMUM,
    NAMES,
    candidates,
    connected_groups,
    feature_records,
    fit,
    personalized,
    probability,
    train,
)
from photocull.ranking_service import prepare
from photocull.storage import Repository


def training_fixture():
    rng = np.random.default_rng(125)
    records, examples = {}, []
    for group in range(32):
        split = "train" if group < 24 else "holdout"
        rs = []
        for index in range(4):
            x = rng.normal(0, 0.08, len(NAMES))
            x[1] = index / 3
            identifier = f"{group}-{index}"
            r = dict(
                photo_id=identifier,
                fingerprint=identifier,
                source_versions={},
                x=x.tolist(),
                a=1 - x[1],
                b=1 - x[1],
                group=f"group-{group}",
                partition=split,
                feature_source="perceptual_hash_surrogate",
                context=f"event-{group}",
            )
            rs.append(r)
            records[identifier] = r
        for a in range(4):
            for b in range(a + 1, 4):
                examples.append(
                    dict(
                        a=rs[a],
                        b=rs[b],
                        choice="b",
                        group=f"group-{group}",
                        partition=split,
                        repeat=False,
                        pair_key=f"{rs[a]['photo_id']}|{rs[b]['photo_id']}",
                    )
                )
    return records, examples


def toy_data():
    ps = [photo(i) for i in range(1, 7)]
    return {
        "photos": ps,
        "groups": [
            {"type": "BURST_GROUP", "members": ["2", "3"]},
            {"type": "NEAR_DUPLICATE", "members": ["3", "4"]},
        ],
        "events": {
            "events": [{"id": "e1", "members": ["1", "2"]}, {"id": "e2", "members": ["4", "5"]}],
            "assignments": {},
        },
        "vectors": {},
    }


def test_transitive_group_leakage_prevention():
    data = toy_data()
    groups = connected_groups(data)
    assert len({groups[str(i)] for i in range(1, 6)}) == 1
    assert groups["6"] != groups["1"]
    records = feature_records(data)
    store = PreferenceStore()
    store.allocate(records)
    assert len({r["partition"] for i, r in records.items() if i != "6"}) == 1


def test_sticky_holdout_quarantine_after_manual_merge():
    data = toy_data()
    records = feature_records(data)
    state = {}
    store = PreferenceStore(state=state)
    store.allocate(records)
    state["partitions"][("1", records["1"]["fingerprint"])] = ("holdout", records["1"]["group"])
    state["partitions"][("6", records["6"]["fingerprint"])] = ("train", records["6"]["group"])
    data["groups"].append({"type": "NEAR_DUPLICATE", "members": ["1", "6"]})
    updated = feature_records(data)
    store.allocate(updated)
    assert {r["partition"] for r in updated.values()} == {"holdout"}


def test_feature_dimensions_and_pairwise_symmetry():
    records, examples = training_fixture()
    model = fit(examples[:100])
    a, b = records["0-0"]["x"], records["0-3"]["x"]
    assert len(model["coefficients"]) == len(NAMES) == 15
    assert probability(model, a, b) < 0.5
    assert probability(model, a, b) + probability(model, b, a) == pytest.approx(1)
    assert probability(model, a, a) == 0.5
    reversed_examples = [dict(e, a=e["b"], b=e["a"], choice="a") for e in examples[:100]]
    reversed_model = fit(reversed_examples)
    assert reversed_model["coefficients"] == pytest.approx(model["coefficients"])


def test_ties_skips_and_repeats_excluded_from_binary_fit():
    _, examples = training_fixture()
    model = fit(examples[:20])
    ignored = [dict(e, choice=c) for e in examples[20:40] for c in ("tie", "skip")]
    repeated = [dict(e, repeat=True, choice="a") for e in examples[40:50]]
    updated = fit(examples[:20] + ignored + repeated)
    assert updated["coefficients"] == model["coefficients"]


def test_minimum_and_group_activation_guard():
    _, examples = training_fixture()
    assert not train(examples[: MINIMUM - 1])["active"]
    single = [dict(e, group="one", partition="train") for e in examples[:60]]
    assert not train(single)["active"]
    no_holdout = [e for e in examples if e["partition"] == "train"]
    model = train(no_holdout)
    assert not model["active"] and model["evaluation"]["groups"] == 0


def test_model_activation_and_grouped_validation():
    _, examples = training_fixture()
    model = train(examples)
    assert model["active"]
    assert not set(model["train_groups"]) & set(model["test_groups"])
    assert model["evaluation"]["rankings"]["C"]["pairwise_accuracy"] > 0.9
    assert model["evaluation"]["rankings"]["A"]["pairwise_accuracy"] == 0
    assert model["evaluation"]["rankings"]["C"]["ndcg"] is None
    assert all(0 <= value <= 1 for value in model["sign_stability"])


def test_no_assumption_that_c_wins():
    _, examples = training_fixture()
    matching = [
        dict(
            e,
            a=dict(e["a"], a=e["a"]["x"][1], b=e["a"]["x"][1]),
            b=dict(e["b"], a=e["b"]["x"][1], b=e["b"]["x"][1]),
        )
        for e in examples
    ]
    assert not train(matching)["active"]


@pytest.mark.parametrize("persistent", [False, True])
def test_feedback_correction_undo_reset_and_model_persistence(tmp_path, persistent):
    repo = Repository(tmp_path / "metadata.db") if persistent else None
    store = PreferenceStore(repo)
    rs = feature_records(toy_data())
    store.allocate(rs)
    identifier = store.save(rs["1"], rs["2"], "a")
    first = store.model(rs)
    assert not first["active"]
    assert store.model(rs)["training_hash"] == first["training_hash"]
    with pytest.raises(ValueError):
        store.save(rs["1"], rs["2"], "b")
    store.correct(identifier, "b")
    assert store.feedback()[0]["choice"] == "b"
    assert store.model(rs)["training_hash"] != first["training_hash"]
    assert store.undo()
    assert store.feedback()[0]["choice"] == "a"
    store.save(rs["1"], rs["2"], "a", repeat=True)
    assert consistency(store.examples(rs))["agreement"] == 1
    assert store.undo() and len(store.feedback()) == 1
    assert store.undo() and not store.feedback()
    store.reset()
    assert not store.feedback() and not store.undo()
    if repo:
        assert repo.db.execute("PRAGMA user_version").fetchone()[0] == 6
        repo.close()


def test_source_and_feature_invalidation():
    rs = feature_records(toy_data())
    store = PreferenceStore()
    store.allocate(rs)
    store.save(rs["1"], rs["2"], "b")
    rs["1"] = dict(rs["1"], fingerprint="modified")
    assert store.model(rs)["excluded_stale_feedback"] == 1
    assert not store.model(rs)["active"]


def test_pair_generation_no_unrelated_or_repeat_and_uncertainty():
    data = toy_data()
    rs = feature_records(data)
    store = PreferenceStore()
    store.allocate(rs)
    pool = candidates(data, rs)
    assert pool and all("6" not in (p["a"], p["b"]) for p in pool)
    assert len({p["key"] for p in pool}) == len(pool)
    assert not {p["key"] for p in candidates(data, rs, [pool[0]["key"]])} & {pool[0]["key"]}
    model = {"scale": [1] * 15, "coefficients": [0] * 15}
    assert candidates(data, rs, model=model, strategy="uncertainty")
    assert {p["key"] for p in candidates(data, rs, strategy="random")} == {p["key"] for p in pool}


def test_learning_curve_and_grades_no_leakage():
    rs, examples = training_fixture()
    grades = {
        i: {"relevance": int(r["x"][1] * 3), "favorite": r["x"][1] == 1} for i, r in rs.items()
    }
    curve = learning_curve(examples, rs, grades)
    assert [r["comparisons"] for r in curve["curve"]] == [10, 20, 30, 50, 75, 100]
    assert all(r["available"] for r in curve["curve"])
    assert curve["curve"][-1]["graded_ranking"]["C"]["ndcg_at_k"] > 0.9
    bad = examples + [dict(examples[0], partition="holdout")]
    with pytest.raises(ValueError, match="leakage"):
        learning_curve(bad)


def test_personalized_ranking_fallback_and_suppression():
    data = toy_data()
    records = feature_records(data)
    cfg = Config()
    fallback = personalized(data, cfg, {"active": False}, records, k=6)
    assert not fallback["personalization_active"]
    active = {
        "active": True,
        "coefficients": [0] * 15,
        "scale": [1] * 15,
        "mean": [0] * 15,
        "alpha": 0.5,
        "reason": "test",
    }
    result = personalized(data, cfg, active, records, k=6)
    assert result["personalization_active"] and result["version"] == "personalized_ranking_v1"
    ids = {r["photo_id"] for r in result["selected"]}
    assert len(ids & {"2", "3"}) <= 1 and len(ids & {"3", "4"}) <= 1
    assert any("Uncalibrated" in r for r in result["selected"][0]["explanation"])


def test_reset_and_cache_clear_preserve_photo_state(photos, config):
    run = run_sync(photos, config)
    repo = Repository(config.cache_dir / "metadata.db")
    data = prepare(repo, run["run_id"], config)
    records = feature_records(data)
    store = PreferenceStore(repo)
    store.allocate(records)
    pair = candidates(data, records)[0]
    store.save(records[pair["a"]], records[pair["b"]], "tie")
    count = repo.db.execute("SELECT COUNT(*) FROM source_photos").fetchone()[0]
    repo.clear_derived()
    assert len(store.feedback()) == 1
    store.reset()
    assert repo.db.execute("SELECT COUNT(*) FROM source_photos").fetchone()[0] == count
    repo.close()


def test_preferences_ui_local_demo_and_generic_fallback(photos, config, monkeypatch):
    from streamlit.testing.v1 import AppTest

    run_sync(photos, config)
    monkeypatch.setenv("PHOTOCULL_CACHE_DIR", str(config.cache_dir))
    app = AppTest.from_file(Path("src/photocull/ui/app.py").resolve(), default_timeout=20).run()
    app.radio[0].set_value("Preferences").run()
    assert not app.exception
    assert any("Personalization is not active yet." in m.value for m in app.markdown)
    next(c for c in app.checkbox if c.label == "Web Demo · session-only preferences").check().run()
    assert not app.exception
    buttons = [b for b in app.button if b.label == "Prefer A"]
    if buttons:
        buttons[0].click().run()
        assert not app.exception
        repo = Repository(config.cache_dir / "metadata.db")
        assert not PreferenceStore(repo).feedback()
        repo.close()
    next(r for r in app.radio if r.label == "Page").set_value("Best Photos").run()
    next(r for r in app.radio if r.label == "Ranking mode").set_value("Personalized").run()
    assert not app.exception
    assert any("Using frozen generic Ranking B" in i.value for i in app.info)
    assert app.session_state["preference_session_only"] is True


def test_complete_graded_metrics_do_not_impute_favorites():
    rs, examples = training_fixture()
    model = fit(examples[:50])
    model["alpha"] = 0
    grades = {i: {"relevance": 0, "favorite": False} for i in rs}
    m = graded_metrics(rs, grades, model)
    assert m["C"]["favorite_recall_at_k"] is None
    assert m["C"]["ndcg_at_k"] == 0
    assert json.loads(json.dumps(model))["feature_version"] == "preference_features_v1"


def test_active_model_persistence_and_training_leakage_rejection(tmp_path):
    records, examples = training_fixture()
    repo = Repository(tmp_path / "metadata.db")
    store = PreferenceStore(repo)
    store.allocate(records)
    for e in examples:
        store.save(records[e["a"]["photo_id"]], records[e["b"]["photo_id"]], e["choice"])
    model = store.model(records)
    assert model["active"]
    repo.close()
    repo = Repository(tmp_path / "metadata.db")
    loaded = PreferenceStore(repo).model(records)
    assert loaded["coefficients"] == model["coefficients"]
    assert loaded["trained_at"] == model["trained_at"]
    assert loaded["train_groups"] == model["train_groups"]
    assert loaded["feature_version"] == "preference_features_v1"
    repo.close()
    with pytest.raises(ValueError, match="leakage"):
        train(examples + [dict(examples[0], partition="holdout")])


def test_invalid_features_and_regularization_rejected():
    _, examples = training_fixture()
    with pytest.raises(ValueError):
        fit(examples, 0)
    bad = [dict(examples[0], a=dict(examples[0]["a"], x=[float("nan")] * 15))]
    with pytest.raises(ValueError):
        fit(bad)


def test_historical_components_survive_manual_split_without_labels():
    data = toy_data()
    store = PreferenceStore()
    records = feature_records(data)
    store.allocate(records)
    data["groups"] = []
    data["events"]["events"] = [{"id": f"new-{i}", "members": [str(i)]} for i in range(1, 7)]
    updated = feature_records(data)
    store.allocate(updated)
    assert len({updated[str(i)]["group"] for i in range(1, 6)}) == 1


def test_photo_overlap_rejected_even_if_group_names_differ():
    _, examples = training_fixture()
    bad = examples + [dict(examples[0], group="different-name", partition="holdout")]
    with pytest.raises(ValueError, match="Photo leakage"):
        train(bad)
    with pytest.raises(ValueError, match="Photo leakage"):
        learning_curve(bad)


def test_incomplete_grades_and_invalid_labels_not_imputed():
    rs, examples = training_fixture()
    model = fit(examples[:50])
    model["alpha"] = 0
    grades = {next(iter(rs)): {"relevance": 3, "favorite": True}}
    result = graded_metrics(rs, grades, model)
    assert result["C"]["ndcg_at_k"] is None
    assert result["C"]["incomplete_groups_excluded"] == 32
    with pytest.raises(ValueError):
        graded_metrics(rs, {"0-0": {"relevance": 4, "favorite": True}}, model)


def test_forced_web_demo_cannot_enable_persistent_feedback(photos, config, monkeypatch):
    from streamlit.testing.v1 import AppTest

    run_sync(photos, config)
    monkeypatch.setenv("PHOTOCULL_CACHE_DIR", str(config.cache_dir))
    monkeypatch.setenv("PHOTOCULL_WEB_DEMO", "1")
    app = AppTest.from_file(Path("src/photocull/ui/app.py").resolve(), default_timeout=20).run()
    next(r for r in app.radio if r.label == "Page").set_value("Preferences").run()
    toggle = next(c for c in app.checkbox if c.label == "Web Demo · session-only preferences")
    assert toggle.value and toggle.disabled
    repo = Repository(config.cache_dir / "metadata.db")
    assert repo.db.execute("SELECT COUNT(*) FROM preference_partitions").fetchone()[0] == 0
    repo.close()
