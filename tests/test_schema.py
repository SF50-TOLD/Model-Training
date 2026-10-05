import json
import re

import pytest
from jsonschema import Draft202012Validator

from notam_gold.paths import SCHEMA_DOC
from notam_gold.schema import canonicalize, schema, validate
from tests.factories import (
    contaminant,
    declared,
    effect,
    extraction,
    height,
    length,
    obstacle,
    partial,
    reference,
    surface,
)


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
    del value["effects"][0]["surfaceCondition"]
    assert validate(value)


@pytest.mark.parametrize(
    ("value", "path"),
    [
        (extraction(effect(closure="both"), isCanceled=True), "effects"),
        (extraction(obstacles=[obstacle(height=height(100))], isCanceled=True), "obstacles"),
        (extraction(effect("09", "both"), effect("09", "both")), "effects[1]"),
        (
            extraction(
                effect("30", thresholdDisplacement=length(357)),
                effect("30", declaredDistances=declared(LDA=length(3518))),
            ),
            "effects[1]",
        ),
        (extraction(effect(None), effect(None)), "effects[1]"),
        (extraction(effect()), "effects[0]"),
        (extraction(effect(closure="both", partialClosure=partial(length(500)))), "effects[0].partialClosure"),
        (extraction(effect(closure="both", thresholdDisplacement=length(500))), "effects[0].thresholdDisplacement"),
        (
            extraction(effect(closure="both", declaredDistances=declared(TORA=length(500)))),
            "effects[0].declaredDistances",
        ),
        (
            extraction(effect(closure="takeoff", declaredDistances=declared(TORA=length(500)))),
            "effects[0].declaredDistances.TORA",
        ),
        (
            extraction(effect(closure="landing", declaredDistances=declared(LDA=length(500)))),
            "effects[0].declaredDistances.LDA",
        ),
        (extraction(effect(None, partialClosure=partial())), "effects[0].runway"),
        (extraction(effect(None, thresholdDisplacement=length(300))), "effects[0].runway"),
        (extraction(effect(None, declaredDistances=declared(TORA=length(5000)))), "effects[0].runway"),
        (extraction(effect(declaredDistances=declared())), "effects[0].declaredDistances"),
        (extraction(effect(thresholdDisplacement=length(0))), "effects[0].thresholdDisplacement"),
        (extraction(effect(partialClosure=partial(length(0)))), "effects[0].partialClosure.length"),
        (extraction(effect(declaredDistances=declared(LDA=length(-1)))), "effects[0].declaredDistances.LDA"),
        (extraction(effect(surfaceCondition=surface([5, 5]))), "effects[0].surfaceCondition.rwyCC"),
        (extraction(effect(surfaceCondition=surface([7, 5, 5]))), "effects[0].surfaceCondition.rwyCC[0]"),
        (
            extraction(effect(surfaceCondition=surface(None, [contaminant(depth=length(0, "in"))]))),
            "effects[0].surfaceCondition.contaminants[0].depth",
        ),
        (extraction(obstacles=[obstacle()]), "obstacles[0]"),
        (extraction(obstacles=[obstacle(distance=length(2, "nm"))]), "obstacles[0].reference"),
        (extraction(obstacles=[obstacle(height=height(100), reference=reference("ARP"))]), "obstacles[0].reference"),
        (
            extraction(obstacles=[obstacle(distance=length(2, "nm"), reference=reference("departureEnd"))]),
            "obstacles[0].reference.runway",
        ),
        (
            extraction(obstacles=[obstacle(distance=length(2, "nm"), reference=reference("ARP", "09"))]),
            "obstacles[0].reference.runway",
        ),
        (extraction(obstacles=[obstacle(height=height(100), direction=360)]), "obstacles[0].direction"),
        (extraction(obstacles=[obstacle(height=height(0))]), "obstacles[0].height"),
        (extraction(effect("9R", "both")), "effects[0].runway"),
        (extraction(effect("09/27", "both")), "effects[0].runway"),
        (extraction(effect(partialClosure=partial(end="NORTH"))), "effects[0].partialClosure.end"),
    ],
)
def test_semantic_and_schema_problems(value, path):
    assert path in [p for p, _ in problem_paths(value)]


def test_two_obstacles_are_two_entries():
    value = extraction(obstacles=[obstacle(height=height(100)), obstacle(height=height(80))])
    assert validate(value) == []


def test_valid_extraction_has_no_problems():
    value = extraction(
        effect(
            "09R",
            partialClosure=partial(length(1713), "W"),
            declaredDistances=declared(TORA=length(6787), LDA=length(6787)),
        ),
        effect("27L", partialClosure=partial(length(1713), "W")),
        effect("04", "landing", declaredDistances=declared(TORA=length(5000))),
        effect("22", "both"),
        effect(None, surfaceCondition=surface([5, 5, 5], [contaminant("wet", 100)])),
        obstacles=[
            obstacle(height(114, datum="MSL"), length(2.2, "nm"), reference("ARP"), "WNW"),
            obstacle(height(440, datum="MSL"), length(4739), reference("departureEnd", "19")),
            obstacle(height(60), length(1, "nm"), reference("threshold", "03L"), 114.5),
        ],
    )
    assert validate(value) == []


def test_canonical_order():
    value = extraction(
        effect("27L", declaredDistances=declared(TORA=length(1))),
        effect(
            "09R",
            surfaceCondition=surface(
                [5, 5, 5], [contaminant("wet", 100), contaminant("ice", 25), contaminant("wet", 100)]
            ),
        ),
        effect(None, closure="both"),
        obstacles=[
            obstacle(height(300), length(1, "nm"), reference("threshold", "27L"), "N"),
            obstacle(height(114, datum="MSL"), length(2.2, "nm"), reference("ARP"), "WNW"),
            obstacle(height(100), length(1, "nm"), reference("threshold", "09R")),
            obstacle(height(50)),
        ],
    )
    ordered = canonicalize(value)
    assert [e["runway"] for e in ordered["effects"]] == [None, "09R", "27L"]
    assert ordered["effects"][1]["surfaceCondition"]["contaminants"] == [
        contaminant("ice", 25),
        contaminant("wet", 100),
    ]
    assert [(o["reference"] or {}).get("runway") for o in ordered["obstacles"]] == [None, None, "09R", "27L"]
    assert [o["height"]["value"] for o in ordered["obstacles"][:2]] == [50, 114]
