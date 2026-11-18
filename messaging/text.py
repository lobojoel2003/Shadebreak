"""Keep texts cheap: SMS uses the GSM-7 alphabet, and a single character
outside it (such as "á" or "°") switches the whole message to UCS-2, which
cuts a segment from 160 to 70 characters. Spanish keeps ñ, é, ü, ¿ and ¡,
which are in GSM-7; á, í, ó and ú lose their accent."""

from __future__ import annotations

import unicodedata

GSM7 = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
GSM7_EXTENDED = set("^{}\\[~]|€")
REPLACEMENTS = {
    "°": "",
    "·": "-",
    "–": "-",
    "—": "-",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "…": "...",
    " ": " ",
}


def fold_to_gsm(text: str) -> str:
    out = []
    for char in text:
        if char in GSM7 or char in GSM7_EXTENDED:
            out.append(char)
        elif char in REPLACEMENTS:
            out.append(REPLACEMENTS[char])
        else:
            base = unicodedata.normalize("NFKD", char)[0]
            out.append(base if base in GSM7 else "")
    return "".join(out)


def is_gsm(text: str) -> bool:
    return all(char in GSM7 or char in GSM7_EXTENDED for char in text)


def segments(text: str) -> int:
    """How many SMS segments ``text`` will use."""
    if is_gsm(text):
        length = sum(2 if char in GSM7_EXTENDED else 1 for char in text)
        return 1 if length <= 160 else -(-length // 153)
    return 1 if len(text) <= 70 else -(-len(text) // 67)
