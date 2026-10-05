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


def test_an_apron_closure_is_labelled_not_relevant_even_when_it_names_a_runway():
    assert relevance.is_apron_closure("APRON DEICE PAD FOR RWY 03L SPOT 5 AND SPOT 6 CLSD EXC FOR ACFT DEICING OPS")
    assert relevance.is_apron_closure("DTW APRON TXL E2 CLSD")
    assert not relevance.is_apron_closure("DTW TWY H (BTN TWY C AND RWY 03L/21R HLDG POINT) CLSD")
    assert not relevance.is_apron_closure("RWY 09/27 CLSD")
    assert not relevance.is_apron_closure("TWY A CLSD. RWY 09/27 CLSD")
    assert not relevance.is_apron_closure("TWY A8 CLSD DUE TO PARKED ACFT, DIST FM THR RWY 11L 95 M, MAX HGT 39 FT")


def test_rule_negatives_leave_out_evaluated_notams_and_keep_one_per_phrasing():
    records = [
        {"icao_location": "KDTW", "notam_text": "APRON DEICE PAD FOR RWY 03L SPOT 5 CLSD"},
        {"icao_location": "KDTW", "notam_text": "APRON DEICE PAD FOR RWY 03L SPOT 6 CLSD"},
        {"icao_location": "KORD", "notam_text": "RAMP 3 BTN RWY 10L AND TWY C CLSD"},
        {"icao_location": "KSFO", "notam_text": "RWY 28L CLSD"},
    ]
    kept = relevance.rule_negatives(records, excluded={"RAMP 3 BTN RWY 10L AND TWY C CLSD"}, limit=10)
    assert len(kept) == 1 and kept[0].startswith("APRON DEICE PAD")
