"""The seeded review-site data and a page object for driving the site."""

from playwright.sync_api import Page, expect

from tests.factories import contaminant, declared, effect, extraction, length, obstacle, surface

SFO = "KSFO A1/2026"
DTW = "KDTW A2/2026"
BZN = "KBZN A3/2026"
JNU = "PAJN A4/2026"
TPA = "KTPA A5/2026"
MSN = "KMSN A6/2026"
LIRR = "LIRR A7/2026"

# The queue's default order: unreviewed first, highest disagreement score first, then selection rank.
QUEUE = [LIRR, DTW, BZN, SFO, JNU, TPA, MSN]

SFO_LABEL = extraction(
    effect("28L", declaredDistances=declared(length(10810), length(10810), length(10981), length(10275)))
)


def seed(gold_db):
    """Seven NOTAMs covering agreement, field and effect disagreements, cancellation, and no silver label."""
    key = gold_db.add_notam(
        "A1/2026",
        "KSFO",
        "SFO RWY 28L DECLARED DIST: TORA 10810FT TODA 10810FT ASDA 10981FT\nLDA 10275FT.",
        stratum="declared_distances",
        rank=0,
    )
    evidence = [
        {"path": "effects[0].runway", "quote": "RWY 28L"},
        {"path": "effects[0].declaredDistances.TORA", "quote": "TORA 10810FT"},
        {"path": "effects[0].declaredDistances.LDA", "quote": "LDA 10275FT"},
    ]
    a = gold_db.add_silver(key, SFO_LABEL, evidence=evidence, note="Stated for 28L only.")
    b = gold_db.add_silver(key, SFO_LABEL, run="B")
    gold_db.add_disagreement(key, a, b, SFO_LABEL, SFO_LABEL)

    key = gold_db.add_notam("A2/2026", "KDTW", "DTW RWY 09R/27L W 1713FT CLSD.", stratum="partial_closure", rank=1)
    label_a = extraction(effect("09R/27L", "partial", closedLength=length(1713), closedEnd="W"))
    label_b = extraction(effect("09R/27L", "partial", closedLength=length(1700), closedEnd="W"))
    gold_db.add_disagreement(
        key, gold_db.add_silver(key, label_a), gold_db.add_silver(key, label_b, run="B"), label_a, label_b
    )

    key = gold_db.add_notam(
        "A3/2026", "KBZN", "BZN RWY 29G DECLARED DIST: TORA 2298FT", stratum="declared_distances", rank=2
    )
    label_b = extraction(effect("29", declaredDistances=declared(TORA=length(2298))))
    gold_db.add_disagreement(
        key, gold_db.add_silver(key, extraction()), gold_db.add_silver(key, label_b, run="B"), extraction(), label_b
    )

    key = gold_db.add_notam(
        "A4/2026", "PAJN", "RWY 08 FICON 5/5/5 100 PCT WET OBS AT 2609211244.", stratum="ficon_rwycc", rank=3
    )
    gold_db.add_silver(
        key, extraction(effect("08", surfaceCondition=surface([5, 5, 5], [contaminant("wet", None, 100)])))
    )

    key = gold_db.add_notam(
        "A5/2026", "KTPA", "A5/26 NOTAMC A4/26\nE) TPA RWY 01L/19R CLSD\nCANCELED", "C", "cancelled", rank=4
    )
    gold_db.add_silver(key, extraction(isCanceled=True))

    gold_db.add_notam("A6/2026", "KMSN", "RWY 14 PAPI U/S", "C", "plausible_negative", rank=5)

    key = gold_db.add_notam(
        "A7/2026", "LIRR", "NEW OBST ERECTED: TOWER 60M AGL; MAST 45M AGL", stratum="obstacle", rank=6
    )
    label_b = extraction(
        effect(None, obstacle=obstacle(heightAGL=length(60, "m"))),
        effect(None, obstacle=obstacle(heightAGL=length(45, "m"))),
    )
    gold_db.add_disagreement(
        key, gold_db.add_silver(key, extraction()), gold_db.add_silver(key, label_b, run="B"), extraction(), label_b
    )
    gold_db.connection.commit()


class ReviewPage:
    """The review screen, in the reviewer's terms."""

    def __init__(self, page: Page, url: str):
        self.page = page
        self.url = url
        page.route("**/fonts.googleapis.com/**", lambda route: route.abort())
        page.route("**/fonts.gstatic.com/**", lambda route: route.abort())

    def open(self):
        self.page.goto(self.url)
        expect(self.heading).not_to_have_text("Loading…")
        return self

    @property
    def heading(self):
        return self.page.locator(".where strong")

    @property
    def counter(self):
        return self.page.locator(".where .count")

    @property
    def message(self):
        return self.page.locator(".toast")

    @property
    def notam_text(self):
        return self.page.locator(".text")

    def expect_on(self, key: str):
        expect(self.heading).to_have_text(key)

    def go_to(self, key: str):
        """Step through the queue with the Next key until ``key`` is shown."""
        for _ in QUEUE:
            if self.heading.inner_text() == key:
                return
            self.press("j")
            self.page.wait_for_timeout(50)
        self.expect_on(key)

    def press(self, key: str):
        self.page.keyboard.press(key)

    def leave_field(self):
        self.press("Escape")

    def effect(self, number: int):
        return self.page.locator("fieldset.effect").nth(number - 1)

    def field(self, name: str, within=None):
        return (within or self.page).locator(".field", has=self.page.get_by_text(name, exact=True))

    def choose_closure(self, closure: str, within):
        within.locator(".segmented label", has_text=closure).click()

    def filter_stratum(self, name: str):
        self.page.get_by_role("combobox", name="Stratum").select_option(label=name)

    def filter_status(self, name: str):
        self.page.get_by_role("combobox", name="Show").select_option(label=name)

    def progress(self, stratum: str):
        return self.page.locator(".progress li", has_text=stratum).locator(".n")

    def wait_for_validation(self):
        self.page.wait_for_timeout(400)
