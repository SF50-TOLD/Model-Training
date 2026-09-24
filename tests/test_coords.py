import pytest

from notam_gold.coords import parse_position


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("403906N0734931W", (40.651667, -73.825278)),
        ("OBST CRANE 411100N1120045W (.68NM S OGD)", (41.183333, -112.0125)),
        ("PSN 515318.8779N 0001954.7151W (BREACHWOOD GREEN)", (51.888577, -0.331865)),
        ("THR COORD: 362334.74N \n0252855.38E", (36.392983, 25.482050)),
        ("3353S15110E", (-33.883333, 151.166667)),
    ],
)
def test_parses_dms_positions(text, expected):
    assert parse_position(text) == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("text", ["RWY 09 CLSD", "406906N0734931W", "403906N1934931W", "4039N"])
def test_rejects_malformed_positions(text):
    with pytest.raises(ValueError):
        parse_position(text)
