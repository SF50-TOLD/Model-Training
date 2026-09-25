from notam_gold.review.queue import review_order


def item(key, stratum, status="unreviewed", half="dev", score=0):
    return {"key": key, "stratum": stratum, "status": status, "half": half, "score": score}


def keys(items):
    return [i["key"] for i in review_order(items)]


def test_re_reviews_then_unreviewed_then_decided():
    items = [
        item("done", "obstacle", status="accepted"),
        item("open", "obstacle"),
        item("stale", "obstacle", status="stale"),
    ]
    assert keys(items) == ["stale", "open", "done"]


def test_interleaves_strata_so_the_largest_does_not_crowd_out_the_rest():
    items = [item(f"dt{n}", "displaced_threshold") for n in range(3)] + [
        item("ficon", "ficon_rwycc"),
        item("closure", "full_closure"),
    ]
    assert keys(items) == ["dt0", "closure", "ficon", "dt1", "dt2"]


def test_the_half_and_stratum_with_fewest_gold_labels_goes_first():
    items = [
        item("dev-done-1", "obstacle", status="accepted"),
        item("dev-done-2", "obstacle", status="edited"),
        item("dev-open", "obstacle"),
        item("test-open", "obstacle", half="test"),
    ]
    assert keys(items)[:2] == ["test-open", "dev-open"]


def test_disagreements_lead_within_a_stratum():
    items = [item("calm", "obstacle"), item("disputed", "obstacle", score=4)]
    assert keys(items) == ["disputed", "calm"]
