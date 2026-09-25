"""The exact prompt the SF50 TOLD app sends for a NOTAM."""


def build_prompt(icao_location: str, notam_text: str) -> str:
    """``Location: <icao_location>``, a blank line, then the NOTAM text as the API returns it."""
    return f"Location: {icao_location}\n\n{notam_text}"
