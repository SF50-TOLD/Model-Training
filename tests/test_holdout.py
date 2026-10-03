import pytest

from notam_gold import strata as s
from notam_gold.holdout import QUOTAS, select, zenodo_record
from notam_gold.selection import Candidate

LOCATIONS = {"PBG": "KPBG"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "A078118 NOTAMN Q)KZBWQMRXXIVNBOA0009994439N07328W005 A)KPBG B)1806271400 C)1809250800 "
            "E)RWY 35 THR DISPLACED 4751FT",
            ("KPBG A0781/18", "RWY 35 THR DISPLACED 4751FT", "N", "2018-06-27T14:00:00Z", "2018-09-25T08:00:00Z"),
        ),
        (
            "B371818 NOTAMN Q)NZZCQMRLC A)NZPM B)1806221800 C)1806240600 E)RWY 25 CLSD F)SFC G)500FT",
            ("NZPM B3718/18", "RWY 25 CLSD", "N", "2018-06-22T18:00:00Z", "2018-06-24T06:00:00Z"),
        ),
        (
            "A102218 NOTAMC A0781/18 Q)KZBWQMRXX A)KPBG B)1807011200 E)RWY 35 THR DISPLACED CANCELED",
            ("KPBG A1022/18", None, "C", "2018-07-01T12:00:00Z", None),
        ),
        (
            "!PBG 06012 PBG RWY 17 FIRST 1000FT CLSD 2305052108-PERM",
            ("KPBG PBG 06012", "PBG RWY 17 FIRST 1000FT CLSD", "N", "2023-05-05T21:08:00Z", None),
        ),
    ],
)
def test_zenodo_notams_become_api_shaped_records(raw, expected):
    record = zenodo_record("", raw, LOCATIONS)
    key, text, kind, start, end = expected
    assert (record["id"], record["nms_type"], record["effective_start"], record["effective_end"]) == (
        key,
        kind,
        start,
        end,
    )
    assert record["notam_text"] == (text or raw)


def test_unrecoverable_zenodo_notams_are_dropped():
    assert zenodo_record("", "!XYZ 06012 XYZ RWY 17 CLSD 2305052108-PERM", LOCATIONS) is None
    assert zenodo_record("EGLL", "free text without a NOTAM header", LOCATIONS) is None


def candidates(prefix, count, stratum):
    return [Candidate(f"{prefix}{n}", f"K{prefix}{n % 9}", (stratum,), ("X", f"{prefix}{n}")) for n in range(count)]


def test_collected_api_notams_fill_each_stratum_before_zenodo():
    api = candidates("API", 5, s.DISPLACED_THRESHOLD) + candidates("APIC", 40, s.FULL_CLOSURE)
    zenodo = candidates("ZEN", 40, s.DISPLACED_THRESHOLD) + candidates("ZENC", 40, s.FULL_CLOSURE)

    selected = select(api, zenodo)

    displaced = [c.id for c, stratum in selected if stratum == s.DISPLACED_THRESHOLD]
    closures = [c.id for c, stratum in selected if stratum == s.FULL_CLOSURE]
    assert len(displaced) == QUOTAS[s.DISPLACED_THRESHOLD] and set(displaced) >= {c.id for c in api[:5]}
    assert len(closures) == QUOTAS[s.FULL_CLOSURE] and all(key.startswith("APIC") for key in closures)
