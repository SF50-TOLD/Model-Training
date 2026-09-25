from tests.factories import effect, extraction, length, obstacle
from training.label_rules import corrected


def test_a_closure_for_landing_only_is_not_a_closure():
    label = extraction(effect("20", "full"))
    assert corrected(label, "RWY 02/20 WIP. RWY 20 CLSD LDG, AVBL TKOF FM TWY A4.") == extraction()


def test_a_closure_written_operation_first_is_not_a_closure():
    label = extraction(effect("16R", "full"))
    assert corrected(label, "LDG RWY 16R NOT AVBL DUE WIP") == extraction()


def test_keeps_an_outright_closure_of_the_same_runway():
    label = extraction(effect("20", "full"))
    assert corrected(label, "RWY 20 CLSD LDG 0600-1200. RWY 20 CLSD 1200-1800.") == label


def test_keeps_what_else_an_effect_states():
    label = extraction(effect("20", "full", thresholdDisplacement=length(300)))
    assert corrected(label, "RWY 20 CLSD FOR LDG. THR 20 DSPLCD 300FT.") == extraction(
        effect("20", thresholdDisplacement=length(300))
    )


def test_an_en_route_obstacle_list_records_no_obstacle():
    label = extraction(effect(None, obstacle=obstacle(heightAGL=length(390))))
    text = "LOW FLYING ZONE BOAT CENTRO SUD OBSTACLES NEW OBST ERECTED: RADIO LINK TOWER HGT AGL 390FT"
    assert corrected(label, text) == extraction()


def test_an_aerodrome_obstacle_is_kept():
    label = extraction(effect("24L", obstacle=obstacle(heightAGL=length(315))))
    assert corrected(label, "TOWER CRANE APRX 430FT BFR THR 24L. 315FT AGL 375FT AMSL.") == label
