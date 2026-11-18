"""Phone numbers in E.164 form (+16025550142). U.S. numbers may be typed
without the country code."""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


def normalize_phone(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        number = "+" + digits
    elif len(digits) == 10:
        number = "+1" + digits
    elif len(digits) == 11 and digits.startswith("1"):
        number = "+" + digits
    else:
        raise ValidationError(_("Enter a 10-digit U.S. number or a full number starting with +."))
    if not 8 <= len(number) - 1 <= 15:
        raise ValidationError(_("That phone number is not the right length."))
    return number


def display_phone(number: str) -> str:
    if re.fullmatch(r"\+1\d{10}", number or ""):
        return f"({number[2:5]}) {number[5:8]}-{number[8:]}"
    return number or ""
