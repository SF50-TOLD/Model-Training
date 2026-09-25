"""End-to-end tests of the review site: a real browser against the app over a seeded temporary database."""

from playwright.sync_api import expect

from tests.e2e.site import BZN, DTW, JNU, LIRR, MSN, ORD, ORD_NEW_RULES, QUEUE, SFO, SFO_LABEL, TPA, after
from tests.factories import contaminant, declared, effect, extraction, length, obstacle, surface


def test_opens_on_re_reviews_then_one_notam_per_stratum(review):
    review.expect_on(ORD)
    expect(review.counter).to_have_text(f"1 of {len(QUEUE)}")
    review.press("j")
    review.expect_on(SFO)
    expect(review.chip("Dev half")).to_be_visible()
    expect(review.page.locator(".progress li")).to_have_count(7)
    expect(review.progress("Obstacle")).to_have_text("0/1")


def test_shows_the_notam_with_evidence_note_and_provenance(review):
    review.go_to(SFO)
    expect(review.notam_text).to_have_text(
        "Location: KSFO\n\nSFO RWY 28L DECLARED DIST: TORA 10810FT TODA 10810FT ASDA 10981FT\nLDA 10275FT."
    )
    expect(review.notam_text.locator(".ev")).to_have_text(["RWY 28L", "TORA 10810FT", "LDA 10275FT"])
    expect(review.page.get_by_text("Stated for 28L only.")).to_be_visible()
    expect(review.page.get_by_text("Prefilled from run A: claude-opus-5-5")).to_be_visible()
    expect(review.page.locator(".chip.primary")).to_have_text("Declared distances")


def test_focusing_a_field_highlights_its_evidence(review):
    review.go_to(SFO)
    review.page.get_by_role("spinbutton", name="TORA").focus()
    expect(review.notam_text.locator(".lit")).to_have_text(["TORA 10810FT"])
    review.page.get_by_role("spinbutton", name="LDA").focus()
    expect(review.notam_text.locator(".lit")).to_have_text(["LDA 10275FT"])


def test_accepting_saves_the_silver_label_and_advances(review, gold_db):
    review.go_to(SFO)
    review.press("a")
    review.expect_on(after(SFO))
    expect(review.message).to_have_text(f"Saved {SFO} as accepted.")
    expect(review.progress("Declared distances")).to_have_text("1/2")
    [saved] = gold_db.reviews(SFO)
    assert (saved["status"], saved["edited"], saved["reviewer"]) == ("accepted", 0, "Tester")
    assert saved["extraction"] == SFO_LABEL


def test_editing_a_value_then_saving_records_an_edit(review, gold_db):
    review.go_to(SFO)
    review.page.get_by_role("spinbutton", name="TORA").fill("10800")
    review.press("Meta+Enter")
    review.expect_on(after(SFO))
    [saved] = gold_db.reviews(SFO)
    assert (saved["status"], saved["edited"]) == ("edited", 1)
    assert saved["extraction"]["effects"][0]["declaredDistances"]["TORA"] == length(10800)


def test_save_key_without_changes_counts_as_accepted(review, gold_db):
    review.go_to(SFO)
    review.press("s")
    review.expect_on(after(SFO))
    assert gold_db.reviews(SFO)[0]["status"] == "accepted"


def test_invalid_labels_show_inline_problems_and_are_not_saved(review, gold_db):
    review.go_to(SFO)
    review.page.get_by_role("spinbutton", name="TORA").fill("")
    expect(review.field("TORA").locator(".problem")).to_have_text("Enter a value")
    review.leave_field()
    review.press("a")
    expect(review.message).to_have_text("Fix the highlighted problems before saving.")
    review.expect_on(SFO)
    assert gold_db.reviews(SFO) == []


def test_marking_ambiguous_keeps_the_note(review, gold_db):
    review.go_to(SFO)
    review.press("n")
    expect(review.page.get_by_label("Note")).to_be_focused()
    review.page.keyboard.type("Table is unclear")
    review.leave_field()
    review.press("m")
    review.expect_on(after(SFO))
    [saved] = gold_db.reviews(SFO)
    assert (saved["status"], saved["note"]) == ("ambiguous", "Table is unclear")
    expect(review.progress("Declared distances")).to_have_text("1/2")


def test_skipping_saves_nothing_toward_progress(review, gold_db):
    review.go_to(SFO)
    review.press("k")
    review.expect_on(after(SFO))
    assert gold_db.reviews(SFO)[0]["status"] == "skipped"
    expect(review.progress("Declared distances")).to_have_text("0/2")


def test_keys_and_buttons_move_through_the_queue(review):
    review.press("j")
    review.expect_on(QUEUE[1])
    review.press("ArrowRight")
    review.expect_on(QUEUE[2])
    review.press("p")
    review.expect_on(QUEUE[1])
    review.press("ArrowLeft")
    review.expect_on(QUEUE[0])
    review.press("p")
    review.expect_on(QUEUE[0])
    review.page.get_by_role("button", name="Next").click()
    review.expect_on(QUEUE[1])
    review.page.get_by_role("button", name="Previous").click()
    review.expect_on(QUEUE[0])


def test_filters_by_stratum_status_and_disagreement(review):
    review.filter_stratum("Partial closure")
    review.expect_on(DTW)
    expect(review.counter).to_have_text("1 of 1")

    review.filter_stratum("All")
    review.page.get_by_label("Runs disagree").check()
    expect(review.counter).to_have_text("1 of 3")
    review.page.get_by_label("Runs disagree").uncheck()

    review.filter_status("Accepted or edited")
    expect(review.page.get_by_text("Nothing matches these filters.")).to_be_visible()

    review.filter_status("All")
    review.page.locator(".progress li", has_text="Condition report with RwyCC").click()
    review.expect_on(JNU)
    expect(review.counter).to_have_text("1 of 1")


def test_reviewed_notams_leave_the_unreviewed_filter(review):
    review.go_to(SFO)
    review.press("a")
    expect(review.message).to_have_text(f"Saved {SFO} as accepted.")
    review.filter_status("Unreviewed")
    expect(review.counter).to_have_text(f"1 of {len(QUEUE) - 2}")
    review.filter_status("Accepted or edited")
    review.expect_on(SFO)
    expect(review.page.locator(".status-pill")).to_have_text("Accepted")


def test_a_reviewed_notam_reopens_with_its_saved_label(review):
    review.go_to(SFO)
    review.page.get_by_role("spinbutton", name="TORA").fill("10800")
    review.leave_field()
    review.press("s")
    review.expect_on(after(SFO))
    review.press("p")
    review.expect_on(SFO)
    expect(review.page.get_by_role("spinbutton", name="TORA")).to_have_value("10800")
    expect(review.page.get_by_text("Last reviewed by Tester")).to_be_visible()


def test_a_field_disagreement_shows_run_b_and_can_take_it(review, gold_db):
    review.go_to(DTW)
    closed_length = review.field("Closed length")
    expect(closed_length.locator(".flag")).to_contain_text("Run B: 1700 ft")
    closed_length.get_by_role("button", name="Use run B").click()
    expect(review.page.get_by_role("spinbutton", name="Closed length")).to_have_value("1700")
    review.press("a")
    review.expect_on(after(DTW))
    [saved] = gold_db.reviews(DTW)
    assert saved["status"] == "edited"
    assert saved["extraction"]["effects"][0]["closedLength"] == length(1700)


def test_an_effect_only_run_b_found_can_be_added(review, gold_db):
    review.go_to(BZN)
    expect(review.page.get_by_text("No effects.")).to_be_visible()
    review.page.get_by_role("button", name="Add run B's effect").click()
    expect(review.page.get_by_role("textbox", name="Runway")).to_have_value("29")
    review.press("s")
    review.expect_on(after(BZN))
    assert gold_db.reviews(BZN)[0]["extraction"] == extraction(
        effect("29", declaredDistances=declared(TORA=length(2298)))
    )


def test_all_of_run_bs_extra_effects_can_be_added_at_once(review):
    review.go_to(LIRR)
    review.page.get_by_role("button", name="Add all 2 of run B's extra effects").click()
    expect(review.page.locator("fieldset.effect")).to_have_count(2)
    heights = review.page.get_by_role("spinbutton", name="Height AGL")
    expect(heights.nth(0)).to_have_value("60")
    expect(heights.nth(1)).to_have_value("45")


def test_effects_can_be_removed(review, gold_db):
    review.go_to(SFO)
    review.page.get_by_role("button", name="Remove effect 1").click()
    expect(review.page.get_by_text("No effects.")).to_be_visible()
    review.press("s")
    review.expect_on(after(SFO))
    assert gold_db.reviews(SFO)[0]["extraction"] == extraction()


def test_building_a_closure_and_declared_distances_from_scratch(review, gold_db):
    review.go_to(MSN)
    expect(review.page.get_by_text("No silver label yet; the form starts empty.")).to_be_visible()
    expect(review.page.get_by_text("Cancelled in metadata only")).to_be_visible()
    review.page.get_by_role("button", name="Add effect").click()
    card = review.effect(1)
    card.get_by_role("textbox", name="Runway").fill("14")
    review.choose_closure("partial", card)
    review.field("Closed length", card).get_by_label("Stated").check()
    card.get_by_role("spinbutton", name="Closed length").fill("500")
    card.get_by_role("combobox", name="Closed length unit").select_option("m")
    card.get_by_role("textbox", name="Closed end").fill("n")
    review.field("Threshold displacement", card).get_by_label("Stated").check()
    card.get_by_role("spinbutton", name="Threshold displacement").fill("200")
    card.get_by_label("Declared distances").check()
    review.field("LDA", card).get_by_label("Stated").check()
    card.get_by_role("spinbutton", name="LDA").fill("3000")
    review.leave_field()
    review.press("s")
    expect(review.message).to_have_text(f"Saved {MSN} as edited.")
    [saved] = gold_db.reviews(MSN)
    assert saved["status"] == "edited"
    assert saved["extraction"] == extraction(
        effect(
            "14",
            "partial",
            closedLength=length(500, "m"),
            closedEnd="N",
            thresholdDisplacement=length(200),
            declaredDistances=declared(LDA=length(3000)),
        )
    )


def test_editing_a_surface_condition_and_its_contaminants(review, gold_db):
    review.go_to(JNU)
    card = review.effect(1)
    expect(card.get_by_role("textbox", name="RwyCC")).to_have_value("5/5/5")
    card.get_by_role("textbox", name="RwyCC").fill("5/3/3")
    card.get_by_role("button", name="Add contaminant").click()
    second = card.locator(".contaminant").nth(1)
    second.get_by_label("Type").select_option("ice")
    second.get_by_role("spinbutton", name="%").fill("10")
    second.get_by_label("Depth stated").check()
    second.get_by_role("spinbutton", name="Depth").fill("0.125")
    card.get_by_role("button", name="Add contaminant").click()
    card.get_by_role("button", name="Remove contaminant").nth(2).click()
    expect(card.locator(".contaminant")).to_have_count(2)
    review.leave_field()
    review.press("s")
    review.expect_on(after(JNU))
    assert gold_db.reviews(JNU)[0]["extraction"] == extraction(
        effect(
            "08",
            surfaceCondition=surface(
                [5, 3, 3],
                [contaminant("wet", None, 100), contaminant("ice", None, 10, {"value": 0.125, "unit": "in"})],
            ),
        )
    )


def test_per_third_contaminants_must_all_have_a_third(review):
    review.go_to(JNU)
    card = review.effect(1)
    card.get_by_role("button", name="Add contaminant").click()
    card.locator(".contaminant").nth(0).get_by_role("spinbutton", name="Third").fill("1")
    expect(card.locator(".contaminants > .problem")).to_have_text(
        "Give every contaminant a runwayThird, or none of them"
    )


def test_an_obstacle_position_can_be_pasted_as_dms(review, gold_db):
    review.go_to(MSN)
    review.page.get_by_role("button", name="Add effect").click()
    card = review.effect(1)
    card.get_by_label("Obstacle").check()
    review.field("Height AGL", card).get_by_label("Stated").check()
    card.get_by_role("spinbutton", name="Height AGL").fill("100")
    card.get_by_role("textbox", name="Distance from").fill("JFK")
    card.get_by_label("Paste a DMS position").fill("403906N0734931W")
    card.get_by_label("Paste a DMS position").press("Tab")
    expect(card.get_by_role("spinbutton", name="Latitude")).to_have_value("40.651667")
    expect(card.get_by_role("spinbutton", name="Longitude")).to_have_value("-73.825278")
    card.get_by_role("textbox", name="Runway").fill("")
    review.leave_field()
    review.press("s")
    expect(review.message).to_have_text(f"Saved {MSN} as edited.")
    assert gold_db.reviews(MSN)[0]["extraction"] == extraction(
        effect(
            None,
            obstacle=obstacle(heightAGL=length(100), distanceReference="JFK", latitude=40.651667, longitude=-73.825278),
        )
    )


def test_a_bad_dms_position_explains_itself(review):
    review.go_to(MSN)
    review.page.get_by_role("button", name="Add effect").click()
    card = review.effect(1)
    card.get_by_label("Obstacle").check()
    card.get_by_label("Paste a DMS position").fill("nonsense")
    card.get_by_label("Paste a DMS position").press("Tab")
    expect(review.message).to_have_text("That isn't a DMS position like 403906N0734931W.")


def test_cancellations_keep_their_flag(review, gold_db):
    review.go_to(TPA)
    expect(review.page.get_by_label("Cancellation")).to_be_checked()
    review.press("a")
    expect(review.message).to_have_text(f"Saved {TPA} as accepted.")
    assert gold_db.reviews(TPA)[0]["extraction"] == extraction(isCanceled=True)


def test_a_cancellation_with_effects_is_rejected(review):
    review.go_to(TPA)
    review.page.get_by_role("button", name="Add effect").click()
    review.choose_closure("full", review.effect(1))
    expect(review.page.locator("form > .problem")).to_have_text("A cancelled NOTAM has no effects")


def test_help_overlay_opens_and_closes(review):
    help_dialog = review.page.get_by_role("dialog", name="Keyboard shortcuts")
    expect(help_dialog).to_be_hidden()
    review.press("?")
    expect(help_dialog).to_be_visible()
    review.press("Escape")
    expect(help_dialog).to_be_hidden()


def test_shortcuts_do_not_fire_while_typing(review, gold_db):
    review.go_to(SFO)
    review.press("n")
    review.page.keyboard.type("jam")
    expect(review.page.get_by_label("Note")).to_have_value("jam")
    review.expect_on(SFO)
    assert gold_db.reviews(SFO) == []


def test_a_review_overtaken_by_new_rules_comes_back_for_re_review(review, gold_db):
    expect(review.progress("Full closure")).to_have_text("0/1")
    review.filter_status("Needs re-review")
    review.expect_on(ORD)
    expect(review.page.locator(".status-pill")).to_have_text("Needs re-review")
    banner = review.page.get_by_role("note")
    expect(banner).to_contain_text("The labelling rules changed after this was saved as accepted.")
    expect(banner).to_contain_text("effects[B:0]")
    expect(review.page.get_by_role("textbox", name="Runway")).to_have_value("10L/28R")

    banner.get_by_role("button", name="Restore my saved label").click()
    expect(review.page.get_by_text("No effects.")).to_be_visible()
    review.page.reload()

    review.filter_status("Needs re-review")
    review.press("a")
    expect(review.message).to_have_text(f"Saved {ORD} as accepted.")
    assert gold_db.reviews(ORD)[-1]["extraction"] == ORD_NEW_RULES
    expect(review.progress("Full closure")).to_have_text("1/1")
    review.filter_status("Needs re-review")
    expect(review.page.get_by_text("Nothing matches these filters.")).to_be_visible()


def test_filters_to_one_half_with_that_halfs_progress(review):
    review.filter_half("Test half")
    expect(review.counter).to_have_text("1 of 6")
    expect(review.chip("Test half")).to_be_visible()
    expect(review.progress("Declared distances")).to_have_text("0/1")
    review.filter_half("Dev half")
    review.expect_on(SFO)
    expect(review.counter).to_have_text("1 of 2")


def test_filters_survive_a_reload(review):
    review.filter_half("Test half")
    review.filter_stratum("Partial closure")
    review.page.reload()
    review.expect_on(DTW)
    expect(review.page.get_by_role("combobox", name="Half")).to_have_value("test")


def test_a_link_opens_a_particular_notam(review):
    review.page.goto(f"{review.url}/?key={JNU}")
    review.expect_on(JNU)
