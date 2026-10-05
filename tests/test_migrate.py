import pytest

from notam_gold import migrate
from notam_gold.reviews import UNREVIEWED_REVIEWER_PREFIX
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


def old_effect(runway="09", closure="none", **fields):
    return {
        "runway": runway,
        "closure": closure,
        "closedLength": None,
        "closedEnd": None,
        "thresholdDisplacement": None,
        "declaredDistances": None,
        "surfaceCondition": None,
        "obstacle": None,
    } | fields


def old_declared(TORA=None, TODA=None, ASDA=None, LDA=None):  # noqa: N803
    return {"TORA": TORA, "TODA": TODA, "ASDA": ASDA, "LDA": LDA}


def old_contaminant(type="wet", runwayThird=None, coveragePercent=None, depth=None):  # noqa: A002, N803
    return {"type": type, "runwayThird": runwayThird, "coveragePercent": coveragePercent, "depth": depth}


def old_obstacle(**fields):
    return {
        "heightAGL": None,
        "heightMSL": None,
        "distance": None,
        "distanceReference": None,
        "bearingDegrees": None,
        "latitude": None,
        "longitude": None,
    } | fields


def old_extraction(*effects, isCanceled=False):  # noqa: N803
    return {"isCanceled": isCanceled, "effects": list(effects)}


def migrated(value, text=""):
    return migrate.migrate(value, text)[0]


def review_notes(value, text=""):
    return [note for note in migrate.migrate(value, text)[1] if note.needs_review]


def test_a_pair_expands_into_one_effect_per_direction_merged_with_its_own_effects():
    value = old_extraction(
        old_effect("09R/27L", "partial", closedLength=length(1713), closedEnd="W"),
        old_effect("09R", declaredDistances=old_declared(length(6787), length(6787), length(6787), length(6100))),
        old_effect("27L", declaredDistances=old_declared(length(6787), length(6787), length(6787), length(6787))),
    )
    assert migrated(value) == extraction(
        effect(
            "09R", partialClosure=partial(length(1713), "W"), declaredDistances=declared(length(6787), length(6100))
        ),
        effect(
            "27L", partialClosure=partial(length(1713), "W"), declaredDistances=declared(length(6787), length(6787))
        ),
    )
    assert review_notes(value) == []


def test_expanded_directions_share_no_objects():
    value = old_extraction(old_effect("12R/30L", declaredDistances=old_declared(LDA=length(320, "m"))))
    first, second = migrated(value)["effects"]
    assert first["declaredDistances"] == second["declaredDistances"]
    assert first["declaredDistances"]["LDA"] is not second["declaredDistances"]["LDA"]


def test_a_full_closure_closes_both_operations():
    assert migrated(old_extraction(old_effect("02/20", "full"))) == extraction(
        effect("02", "both"), effect("20", "both")
    )


def test_a_full_closure_the_text_limits_to_one_operation_is_flagged_and_narrowed():
    text = "RWY 24 CLSD FOR TKOF AND LDG. RWY 06 CLSD FOR LDG DUE WIP."
    value = old_extraction(old_effect("24", "full"), old_effect("06", "full"))
    assert migrated(value, text) == extraction(effect("06", "landing"), effect("24", "both"))
    assert [note.path for note in review_notes(value, text)] == ["effects[0].closure"]


def test_a_one_operation_closure_the_old_label_left_out_is_flagged_but_not_invented():
    text = "RWY 02/20 WIP. RWY 20 CLSD LDG, AVBL TKOF FM TWY A4."
    assert migrated(old_extraction(), text) == extraction()
    assert [note.path for note in review_notes(old_extraction(), text)] == ["effects"]


def test_declared_distances_without_tora_or_lda_are_dropped_with_their_effect():
    value = old_extraction(old_effect("27", declaredDistances=old_declared(TODA=length(5000), ASDA=length(5000))))
    new, notes = migrate.migrate(value)
    assert new == extraction()
    assert notes and not any(note.needs_review for note in notes)


def test_contaminant_thirds_are_dropped_and_duplicates_collapse():
    condition = {"rwyCC": [5, 5, 5], "contaminants": [old_contaminant("wet", third, 100) for third in (1, 2, 3)]}
    value = old_extraction(old_effect("16", surfaceCondition=condition))
    assert migrated(value) == extraction(effect("16", surfaceCondition=surface([5, 5, 5], [contaminant("wet", 100)])))


def test_an_obstacle_moves_to_the_top_level_with_its_reference_and_direction_read_from_the_text():
    text = "JFK OBST CRANE (ASN 2024-AEA-1234-OE) 404016N0734931W (2.2NM WNW JFK) 114FT (104FT AGL) FLAGGED"
    value = old_extraction(
        old_effect(
            None,
            obstacle=old_obstacle(
                heightAGL=length(104),
                heightMSL=length(114),
                distance=length(2.2, "nm"),
                distanceReference="JFK",
                latitude=40.671111,
                longitude=-73.825278,
            ),
        )
    )
    assert migrated(value, text) == extraction(
        obstacles=[obstacle(height(114, datum="MSL"), length(2.2, "nm"), reference("ARP"), "WNW")]
    )
    assert [note.path for note in review_notes(value, text)] == ["obstacles[0].direction"]


@pytest.mark.parametrize(
    ("written", "runway", "expected"),
    [
        ("APCH END RWY 03L", None, reference("threshold", "03L")),
        ("THR 19", None, reference("threshold", "19")),
        ("DER", "19", reference("departureEnd", "19")),
        ("DEP-END RWY 23", None, reference("departureEnd", "23")),
        ("TORA RWY 18C", "18C", reference("departureEnd", "18C")),
        ("TODA RWY 06", None, reference("departureEnd", "06")),
        ("ARP LFBL", None, reference("ARP")),
        ("PBI", None, reference("ARP")),
    ],
)
def test_references_that_name_a_known_point_map_without_review(written, runway, expected):
    value = old_extraction(
        old_effect(runway, obstacle=old_obstacle(distance=length(1, "nm"), distanceReference=written))
    )
    text = "TOWER CRANE 1NM FROM " + written if "TO" not in written else f"CRANE 1NM BEYOND {written}"
    assert migrated(value, text)["obstacles"][0]["reference"] == expected
    assert review_notes(value, text) == []


def test_an_unrecognised_reference_is_other_and_flagged():
    value = old_extraction(
        old_effect(None, obstacle=old_obstacle(distance=length(300, "m"), distanceReference="HELIPAD"))
    )
    assert migrated(value)["obstacles"][0]["reference"] == reference("other")
    assert [note.path for note in review_notes(value)] == ["obstacles[0].reference"]


@pytest.mark.parametrize(("bearing", "direction"), [(114, 114), (360, 0)])
def test_a_numeric_bearing_becomes_the_direction(bearing, direction):
    value = old_extraction(old_effect(None, obstacle=old_obstacle(heightAGL=length(60), bearingDegrees=bearing)))
    assert migrated(value)["obstacles"] == [obstacle(height(60), direction=direction)]


def test_conflicting_values_for_one_direction_keep_the_direction_and_are_flagged():
    value = old_extraction(
        old_effect("09R/27L", "partial", closedLength=length(1713)),
        old_effect("09R", "partial", closedLength=length(1500)),
    )
    new, notes = migrate.migrate(value)
    assert new["effects"][0]["partialClosure"] == partial(length(1500))
    assert [note.path for note in notes if note.needs_review] == ["effects[0].partialClosure"]


def test_current_migrates_old_values_and_leaves_new_ones_alone():
    new = extraction(effect("09", "both"))
    assert migrate.current(new) is new
    assert migrate.current(old_extraction(old_effect("09", "full"))) == new


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("RWY 24 CLSD FOR TKOF AND LDG.", {"24": {"takeoff", "landing"}}),
        ("RWY 13/31 CLSD FOR TAKE-OFF AND LANDING.", {"13": {"takeoff", "landing"}, "31": {"takeoff", "landing"}}),
        ("RWY 07/25 CLSD TO LDG/TKOF TFC", {"07": {"takeoff", "landing"}, "25": {"takeoff", "landing"}}),
        ("RWY 09 CLSD FOR ARR/DEP DUE TO EXER", {"09": {"takeoff", "landing"}}),
        ("LDG RWY 16R NOT AVBL DUE WIP", {"16R": {"landing"}}),
        ("RWY 20 CLSD LDG, AVBL TKOF FM TWY A4.", {"20": {"landing"}}),
        ("RWY 06/24 LIMITED TO ARRIVAL ONLY ON RWY 06", {"06": {"takeoff"}}),
        ("RWY 04R AVBL FOR TKOF ONLY", {"04R": {"landing"}}),
        ("IFR DEP RWY 07 NOT AUTH", {}),
        ("RWY 28L CLSD", {}),
    ],
)
def test_operation_closures_read_from_the_text(text, expected):
    assert migrate.operation_closures(text) == expected


def test_migrating_reviews_appends_a_row_per_current_review_and_queues_the_flagged_ones(gold_db):
    plain = gold_db.add_notam("A1/2026", text="RWY 28L CLSD")
    flagged = gold_db.add_notam("A2/2026", text="RWY 06 CLSD FOR LDG DUE WIP")
    gold_db.add_review(plain, "accepted", old_extraction(old_effect("28L", "full")))
    gold_db.add_review(flagged, "edited", old_extraction(old_effect("06", "full")), edited=True)
    gold_db.connection.commit()

    report = migrate.migrate_reviews(gold_db.connection, dry_run=True)
    assert len(gold_db.reviews(plain)) == 1
    assert report.needs_review == [flagged]

    migrate.migrate_reviews(gold_db.connection, dry_run=False)
    [_, migrated_plain] = gold_db.reviews(plain)
    [_, migrated_flagged] = gold_db.reviews(flagged)
    assert migrated_plain["extraction"] == extraction(effect("28L", "both"))
    assert migrated_plain["status"] == "accepted"
    assert not migrated_plain["reviewer"].startswith(UNREVIEWED_REVIEWER_PREFIX)
    assert migrated_flagged["extraction"] == extraction(effect("06", "landing"))
    assert migrated_flagged["reviewer"].startswith(UNREVIEWED_REVIEWER_PREFIX)
    assert "effects[0].closure" in migrated_flagged["note"]
    assert (migrated_flagged["status"], migrated_flagged["edited"]) == ("edited", 1)
