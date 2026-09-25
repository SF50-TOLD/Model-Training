import json

import pytest

from notam_gold.export import InvalidGoldLabelError, export, split_of
from tests.factories import effect, extraction, length


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_exports_model_samples_with_explicit_nulls_and_aligned_meta(gold_db, tmp_path):
    label = extraction(effect("28L", "partial", closedLength=length(1000)), effect("10R", "full"))
    key = gold_db.add_notam("A1/2026", text="RWY 28L W 1000FT CLSD\nRWY 10R CLSD")
    silver = gold_db.add_silver(key, label)
    gold_db.add_review(key, "accepted", label, silver)
    ambiguous = gold_db.add_notam("A2/2026")
    gold_db.add_review(ambiguous, "ambiguous", extraction())
    superseded = gold_db.add_notam("A3/2026", nms_type="C")
    gold_db.add_review(superseded, "accepted", extraction(effect("28L", "full")))
    gold_db.add_review(superseded, "edited", extraction(), edited=True)

    export(gold_db.connection, tmp_path / "eval")

    samples = read_jsonl(tmp_path / "eval" / "notam_gold.jsonl")
    meta = read_jsonl(tmp_path / "eval" / "notam_gold.meta.jsonl")
    assert samples[0] == {
        "input": {"prompt": "Location: KSFO\n\nRWY 28L W 1000FT CLSD\nRWY 10R CLSD"},
        "output": {"value": {"isCanceled": False, "effects": [effect("10R", "full"), label["effects"][0]]}},
    }
    assert samples[1]["output"]["value"] == extraction()
    assert '"obstacle": null' in (tmp_path / "eval" / "notam_gold.jsonl").read_text()
    assert [m["line"] for m in meta] == [1, 2]
    assert [m["notamId"] for m in meta] == ["A1/2026", "A3/2026"]
    assert meta[0]["silverModel"] == "claude-opus-5-5"
    assert (meta[1]["edited"], meta[1]["metadataCanceled"]) == (True, True)


def test_splits_are_disjoint_and_complete(gold_db, tmp_path):
    for n in range(40):
        gold_db.add_review(gold_db.add_notam(f"B{n}/2026"), "accepted", extraction())
    export(gold_db.connection, tmp_path)
    gold = {m["notamKey"] for m in read_jsonl(tmp_path / "notam_gold.meta.jsonl")}
    dev = {m["notamKey"] for m in read_jsonl(tmp_path / "notam_dev.meta.jsonl")}
    test = {m["notamKey"] for m in read_jsonl(tmp_path / "notam_test.meta.jsonl")}
    assert dev | test == gold and not dev & test
    assert 0.2 < len(dev) / len(gold) < 0.6


def test_split_depends_only_on_identity():
    assert split_of("KSFO A1/2026") == split_of("KSFO A1/2026")
    assert {split_of(f"KSFO A{n}/2026") for n in range(20)} == {"dev", "test"}


def test_refuses_to_export_an_invalid_label(gold_db, tmp_path):
    key = gold_db.add_notam("C1/2026")
    gold_db.add_review(key, "accepted", extraction(effect("28L", "none")))
    with pytest.raises(InvalidGoldLabelError):
        export(gold_db.connection, tmp_path)


def test_leaves_out_reviews_the_labelling_rules_have_changed(gold_db, tmp_path):
    key = gold_db.add_notam("D1/2026")
    gold_db.add_silver(key, extraction(), created_at="2026-09-24T20:00:00+00:00")
    gold_db.add_review(key, "accepted", extraction(), reviewed_at="2026-09-24T21:00:00+00:00")
    gold_db.add_silver(key, extraction(effect("28L", "full")), created_at="2026-09-25T09:00:00+00:00")
    export(gold_db.connection, tmp_path)
    assert (tmp_path / "notam_gold.jsonl").read_text() == ""


def test_worked_examples_are_flagged_and_kept_out_of_the_test_half(gold_db, tmp_path, monkeypatch):
    keys = [gold_db.add_notam(f"E{n}/2026", text=f"RWY {n:02} CLSD") for n in range(1, 30)]
    for key in keys:
        gold_db.add_review(key, "accepted", extraction(effect(f"{int(key.split('E')[1].split('/')[0]):02}", "full")))
    example = next(k for k in keys if split_of(k) == "test")
    example_prompt = (
        "Location: KSFO\n\n"
        + gold_db.connection.execute("SELECT notam_text FROM notam WHERE id = ?", (example,)).fetchone()[0]
    )
    monkeypatch.setattr("notam_gold.export.worked_example_prompts", lambda: {example_prompt})

    export(gold_db.connection, tmp_path)

    gold = {m["notamKey"]: m for m in read_jsonl(tmp_path / "notam_gold.meta.jsonl")}
    test = {m["notamKey"] for m in read_jsonl(tmp_path / "notam_test.meta.jsonl")}
    assert gold[example]["workedExample"] is True
    assert example not in test
    assert sum(not m["workedExample"] for m in gold.values()) == len(keys) - 1
