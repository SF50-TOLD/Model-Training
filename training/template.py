"""How a NOTAM is put to the model, shared by training and the app's manifest (conversion/)."""

PROMPT_TEMPLATE = "<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"
END_OF_READING = "<|im_end|>"


def prompt_text(prompt: str) -> str:
    """The text before the model's reading; ``prompt`` is `Location: <icao>`, a blank line, the NOTAM."""
    return PROMPT_TEMPLATE.replace("{prompt}", prompt)
