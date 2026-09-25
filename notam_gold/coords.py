"""Parse NOTAM degrees-minutes-seconds positions into decimal degrees."""

import re

# Latitude: DDMM[SS[.s]] + N/S. Longitude: DDDMM[SS[.s]] + E/W. Optional whitespace between.
POSITION = re.compile(
    r"(?P<lat>\d{4}(?:\d{2}(?:\.\d+)?)?)\s*(?P<ns>[NS])\s*(?P<lon>\d{5}(?:\d{2}(?:\.\d+)?)?)\s*(?P<ew>[EW])\b"
)


def _degrees(digits: str, degree_width: int) -> float:
    degrees = int(digits[:degree_width])
    minutes = int(digits[degree_width : degree_width + 2])
    seconds = float(digits[degree_width + 2 :] or 0)
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"Invalid minutes/seconds in {digits!r}")
    return degrees + minutes / 60 + seconds / 3600


def parse_position(text: str) -> tuple[float, float]:
    """Parse the first DMS position in ``text`` (e.g. ``403906N0734931W``) into (latitude, longitude).

    Raises ``ValueError`` when no well-formed position is present.
    """
    match = POSITION.search(text.upper())
    if not match:
        raise ValueError(f"No DMS position in {text!r}")
    latitude = _degrees(match["lat"], 2)
    longitude = _degrees(match["lon"], 3)
    if latitude > 90 or longitude > 180:
        raise ValueError(f"Position out of range in {text!r}")
    return (
        round(-latitude if match["ns"] == "S" else latitude, 6),
        round(-longitude if match["ew"] == "W" else longitude, 6),
    )
