import math

from tests.factories import effect, extraction, height, obstacle
from training import relevance


def test_features_are_deterministic_and_unit_length():
    first = relevance.features("RWY 09/27 CLSD DUE WIP")
    assert first == relevance.features("rwy  09/27 clsd due wip")
    assert math.isclose(math.sqrt(sum(v * v for v in first.values())), 1.0)


def test_numbers_do_not_change_features():
    assert relevance.features("RWY 09 W 1713FT CLSD") == relevance.features("RWY 27 W 900FT CLSD")


def test_a_hash_matches_the_published_fnv1a_value():
    assert relevance.fnv1a64("a") == 0xAF63DC4C8601EC8C


def test_a_notam_is_relevant_when_it_states_an_effect_or_an_obstacle():
    assert relevance.is_relevant(extraction(effect("09", "both")))
    assert relevance.is_relevant(extraction(obstacles=[obstacle(height(100))]))
    assert not relevance.is_relevant(extraction())
    assert not relevance.is_relevant(extraction(isCanceled=True))


def test_training_separates_relevant_from_irrelevant_text():
    texts = ["RWY 09 CLSD", "RWY 27 CLSD", "RWY 04 CLSD DUE WIP", "TWY A LGT U/S", "PAPI U/S", "VOR OTS"]
    model = relevance.train(texts, [1, 1, 1, 0, 0, 0], epochs=30)
    assert model.probability("RWY 18 CLSD") > 0.5 > model.probability("TWY B LGT U/S")
