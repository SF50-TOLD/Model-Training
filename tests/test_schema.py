import json
import re

import pytest
from jsonschema import Draft202012Validator

from notam_gold.paths import SCHEMA_DOC
from notam_gold.schema import canonicalize, schema, validate
from tests.factories import contaminant, declared, effect, extraction, length, obstacle, surface


def problem_paths(value):
    return [(p.path, p.message) for p in validate(value)]


def test_schema_is_valid_2020_12():
    Draft202012Validator.check_schema(schema())


def test_schema_doc_examples_are_valid_and_canonical():
    blocks = re.findall(r"```json\n(.*?)\n```", SCHEMA_DOC.read_text(encoding="utf-8"), re.DOTALL)
    assert len(blocks) >= 15
    for block in blocks:
        value = json.loads(block)
        assert validate(value) == []
        assert canonicalize(value) == value


def test_missing_keys_are_schema_errors():
    value = extraction(effect())
    del value["effects"][0]["obstacle"]
    assert validate(value)


@pytest.mark.parametrize(
    ("value", "path"),
    [
        (extraction(effect(closure="full"), isCanceled=True), "effects"),
        (extraction(effect(closure="full", closedLength=length(500))), "effects[0].closedLength"),
        (extraction(effect(closure="none", closedEnd="W", thresholdDisplacement=length(1))), "effects[0].closedEnd"),
        (extraction(effect("09/27", declaredDistances=declared(TORA=length(5000)))), "effects[0].runway"),
        (extraction(effect(None, thresholdDisplacement=length(300))), "effects[0].runway"),
        (extraction(effect()), "effects[0]"),
        (extraction(effect(declaredDistances=declared())), "effects[0].declaredDistances"),
        (extraction(effect(thresholdDisplacement=length(0))), "effects[0].thresholdDisplacement"),
        (extraction(effect(surfaceCondition=surface([5, 5]))), "effects[0].surfaceCondition.rwyCC"),
        (
            extraction(effect(surfaceCondition=surface(None, [contaminant(runwayThird=1), contaminant("ice")]))),
            "effects[0].surfaceCondition.contaminants",
        ),
        (extraction(effect(obstacle=obstacle())), "effects[0].obstacle"),
        (extraction(effect(obstacle=obstacle(latitude=40.0))), "effects[0].obstacle.latitude"),
        (extraction(effect("09", "full"), effect("09", "full")), "effects[1]"),
        (extraction(effect("9R", "full")), "effects[0].runway"),
        (extraction(effect(surfaceCondition=surface([7, 5, 5]))), "effects[0].surfaceCondition.rwyCC[0]"),
    ],
)
def test_semantic_and_schema_problems(value, path):
    assert path in [p for p, _ in problem_paths(value)]


def test_valid_extraction_has_no_problems():
    value = extraction(
        effect("09R/27L", "partial", closedLength=length(1713), closedEnd="W"),
        effect("09R", declaredDistances=declared(TORA=length(6787), LDA=length(6787))),
        effect(None, obstacle=obstacle(heightAGL=length(100), latitude=40.65, longitude=-73.8)),
    )
    assert validate(value) == []


def test_canonical_order():
    value = extraction(
        effect("27L", declaredDistances=declared(TORA=length(1))),
        effect("09R/27L", "partial"),
        effect("09R", "partial"),
        effect("09R", surfaceCondition=surface([5, 5, 5], [contaminant("wet", 2), contaminant("ice", 1)])),
        effect(None, obstacle=obstacle(heightAGL=length(1))),
    )
    ordered = canonicalize(value)["effects"]
    assert [(e["runway"], e["closure"]) for e in ordered] == [
        (None, "none"),
        ("09R", "none"),
        ("09R", "partial"),
        ("09R/27L", "partial"),
        ("27L", "none"),
    ]
    assert [c["runwayThird"] for c in ordered[1]["surfaceCondition"]["contaminants"]] == [1, 2]
