from notam_gold.disagreement import diff, score
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


def paths(a, b):
    return [d.path for d in diff(a, b)]


def test_identical_extractions_agree():
    value = extraction(effect("09", "both"), effect("27", declaredDistances=declared(TORA=length(5000))))
    assert diff(value, value) == []


def test_aligns_effects_by_runway_not_order():
    a = extraction(effect("09", "both"), effect("27", thresholdDisplacement=length(300)))
    b = extraction(effect("27", thresholdDisplacement=length(350)), effect("09", "both"))
    differences = diff(a, b)
    assert [d.path for d in differences] == ["effects[1].thresholdDisplacement.value"]
    assert (differences[0].a, differences[0].b) == (300, 350)


def test_reports_missing_and_extra_effects():
    a = extraction(effect("09", "both"))
    b = extraction(effect("27", "both"))
    assert paths(a, b) == ["effects[0]", "effects[B:0]"]


def test_null_versus_value():
    a = extraction(effect("27", declaredDistances=declared(TORA=length(5000))))
    b = extraction(effect("27", declaredDistances=declared(TORA=length(5000), LDA=length(4000))))
    assert paths(a, b) == ["effects[0].declaredDistances.LDA"]


def test_contaminant_order_does_not_matter_but_content_does():
    first = surface([5, 5, 5], [contaminant("wet", 100), contaminant("ice", 25)])
    swapped = surface([5, 5, 5], [contaminant("ice", 25), contaminant("wet", 100)])
    different = surface([5, 5, 5], [contaminant("ice", 25), contaminant("slush", 100)])
    assert paths(extraction(effect(surfaceCondition=first)), extraction(effect(surfaceCondition=swapped))) == []
    assert paths(extraction(effect(surfaceCondition=first)), extraction(effect(surfaceCondition=different))) == [
        "effects[0].surfaceCondition.contaminants"
    ]


def test_aligns_obstacles_by_referenced_runway_then_order():
    near = obstacle(height(100), length(1, "nm"), reference("threshold", "09"), "N")
    far = obstacle(height(300, datum="MSL"), length(2, "nm"), reference("ARP"), "WNW")
    a = extraction(obstacles=[near, far])
    b = extraction(obstacles=[far, obstacle(height(120), length(1, "nm"), reference("threshold", "09"), "N")])
    assert paths(a, b) == ["obstacles[1].height.value"]
    assert paths(a, extraction(obstacles=[near])) == ["obstacles[0]"]
    assert paths(extraction(obstacles=[near]), a) == ["obstacles[B:0]"]


def test_safety_critical_disagreements_score_higher():
    base = extraction(effect("27", partialClosure=partial(length(1000), "W")))
    end_only = extraction(effect("27", partialClosure=partial(length(1000), "E")))
    closure_only = extraction(effect("27", "landing", partialClosure=partial(length(1000), "W")))
    assert score(diff(base, closure_only)) > score(diff(base, end_only))
