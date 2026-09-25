from notam_gold.disagreement import diff, score
from tests.factories import contaminant, declared, effect, extraction, length, surface


def paths(a, b):
    return [d.path for d in diff(a, b)]


def test_identical_extractions_agree():
    value = extraction(effect("09", "full"), effect("27", declaredDistances=declared(TORA=length(5000))))
    assert diff(value, value) == []


def test_aligns_effects_by_runway_not_order():
    a = extraction(effect("09", "full"), effect("27", thresholdDisplacement=length(300)))
    b = extraction(effect("27", thresholdDisplacement=length(350)), effect("09", "full"))
    differences = diff(a, b)
    assert [d.path for d in differences] == ["effects[1].thresholdDisplacement.value"]
    assert (differences[0].a, differences[0].b) == (300, 350)


def test_reports_missing_and_extra_effects():
    a = extraction(effect("09", "full"))
    b = extraction(effect("27", "full"))
    assert paths(a, b) == ["effects[0]", "effects[B:0]"]


def test_null_versus_value():
    a = extraction(effect("27", declaredDistances=declared(TORA=length(5000))))
    b = extraction(effect("27", declaredDistances=declared(TORA=length(5000), LDA=length(4000))))
    assert paths(a, b) == ["effects[0].declaredDistances.LDA"]


def test_contaminant_order_does_not_matter_but_content_does():
    first = surface([5, 5, 5], [contaminant("wet", 1), contaminant("ice", 2)])
    swapped = surface([5, 5, 5], [contaminant("ice", 2), contaminant("wet", 1)])
    different = surface([5, 5, 5], [contaminant("ice", 2), contaminant("slush", 1)])
    assert paths(extraction(effect(surfaceCondition=first)), extraction(effect(surfaceCondition=swapped))) == []
    assert paths(extraction(effect(surfaceCondition=first)), extraction(effect(surfaceCondition=different))) == [
        "effects[0].surfaceCondition.contaminants"
    ]


def test_safety_critical_disagreements_score_higher():
    base = extraction(effect("27", "partial", closedLength=length(1000), closedEnd="W"))
    end_only = extraction(effect("27", "partial", closedLength=length(1000), closedEnd="E"))
    length_only = extraction(effect("27", "partial", closedLength=length(1200), closedEnd="W"))
    assert score(diff(base, length_only)) > score(diff(base, end_only))
