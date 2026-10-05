from tests.factories import effect, extraction, height, length, obstacle, partial, reference
from training.label_rules import corrected


def test_an_en_route_obstacle_list_records_no_obstacle():
    label = extraction(obstacles=[obstacle(height=height(390))])
    text = "LOW FLYING ZONE BOAT CENTRO SUD OBSTACLES NEW OBST ERECTED: RADIO LINK TOWER HGT AGL 390FT"
    assert corrected(label, text) == extraction()


def test_an_aerodrome_obstacle_is_kept():
    label = extraction(obstacles=[obstacle(height(375, datum="MSL"), length(430), reference("threshold", "24L"))])
    assert corrected(label, "TOWER CRANE APRX 430FT BFR THR 24L. 315FT AGL 375FT AMSL.") == label


def test_a_closure_after_the_last_scheduled_flight_is_not_a_closure():
    label = extraction(effect("16", "both"), effect("34", "both"))
    text = "RWY 16/34 CLSD AFTER LAST SKED INTL ARR DUE WIP. AVBL WITH 60 MIN PN TO ATC"
    assert corrected(label, text) == extraction()


def test_a_portion_closed_after_the_last_scheduled_flight_is_not_a_closure():
    label = extraction(effect("07", partialClosure=partial(length(500), "thresholdEnd")))
    assert corrected(label, "RWY 07 CLSD AFTER LAST SKED FLT FIRST 500FT") == extraction()


def test_keeps_what_else_an_effect_states():
    label = extraction(effect("20", "both", thresholdDisplacement=length(300)))
    assert corrected(label, "RWY 20 CLSD AFTER LAST SKED FLT. THR 20 DSPLCD 300FT.") == extraction(
        effect("20", thresholdDisplacement=length(300))
    )


def test_a_further_displacement_without_its_total_records_no_displacement():
    label = extraction(effect("26", thresholdDisplacement=length(375, "m")))
    assert corrected(label, "DTHR RWY 26 FURTHER DISPLACED 375M DUE SHIP CRANES OPR IN HARBOUR.") == extraction()


def test_a_further_displacement_with_its_total_is_kept():
    label = extraction(effect("31", thresholdDisplacement=length(522)))
    text = "THR 31 FURTHER DISPLACED BY 272FT BEYOND PUBLISHED DTHR DUE TREE. (TOTAL DISPLACEMENT 522FT)."
    assert corrected(label, text) == label
