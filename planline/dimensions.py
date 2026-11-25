"""Conservative parsing of explicitly written architectural dimensions.

The parser never assumes a missing unit and never resolves ambiguous separators.
Its output is an interpretation proposal, not a verified measurement.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


UNIT_TO_MM = {
    "mm": Decimal("1"),
    "cm": Decimal("10"),
    "m": Decimal("1000"),
    "in": Decimal("25.4"),
    "ft": Decimal("304.8"),
}

UNIT_ALIASES = {
    "mm": "mm", "millimeter": "mm", "millimeters": "mm", "millimetre": "mm", "millimetres": "mm",
    "cm": "cm", "centimeter": "cm", "centimeters": "cm", "centimetre": "cm", "centimetres": "cm",
    "m": "m", "meter": "m", "meters": "m", "metre": "m", "metres": "m",
    "in": "in", "inch": "in", "inches": "in",
    "ft": "ft", "foot": "ft", "feet": "ft",
}


def _normalise_number(raw: str) -> tuple[Decimal | None, str | None]:
    value = raw.strip().replace(" ", "")
    if not value:
        return None, "No numeric value was found."
    if not re.fullmatch(r"[+-]?[0-9.,]+", value):
        return None, "The numeric part contains unsupported characters."

    sign = ""
    if value[0] in "+-":
        sign, value = value[0], value[1:]
    if not value:
        return None, "No digits were found."

    if "," in value and "." in value:
        decimal_separator = "," if value.rfind(",") > value.rfind(".") else "."
        grouping_separator = "." if decimal_separator == "," else ","
        integer_part, fractional_part = value.rsplit(decimal_separator, 1)
        groups = integer_part.split(grouping_separator)
        if len(groups) > 1 and (
            not 1 <= len(groups[0]) <= 3
            or any(len(group) != 3 for group in groups[1:])
            or not all(group.isdigit() for group in groups)
        ):
            return None, "The thousands and decimal separators are ambiguous."
        if not fractional_part.isdigit():
            return None, "The decimal part is invalid."
        canonical = "".join(groups) + "." + fractional_part
    elif "," in value:
        if value.count(",") > 1:
            groups = value.split(",")
            if not 1 <= len(groups[0]) <= 3 or any(len(group) != 3 for group in groups[1:]):
                return None, "The comma grouping is ambiguous."
            canonical = "".join(groups)
        else:
            left, right = value.split(",")
            if len(right) == 3 and 1 <= len(left) <= 3:
                canonical = left + right
            else:
                canonical = left + "." + right
    elif "." in value:
        if value.count(".") > 1:
            groups = value.split(".")
            if not 1 <= len(groups[0]) <= 3 or any(len(group) != 3 for group in groups[1:]):
                return None, "The dot grouping is ambiguous."
            return None, "A dot followed by three digits may be a decimal or a thousands separator."
        left, right = value.split(".")
        if len(right) == 3 and 1 <= len(left) <= 3:
            return None, "A dot followed by three digits may be a decimal or a thousands separator."
        canonical = left + "." + right
    else:
        canonical = value

    try:
        number = Decimal(sign + canonical)
    except InvalidOperation:
        return None, "The numeric value is invalid."
    if not number.is_finite():
        return None, "The numeric value must be finite."
    return number, None


def _parse_fraction(raw: str) -> Decimal | None:
    value = raw.strip()
    if re.fullmatch(r"\d+\s+\d+/\d+", value):
        whole, fraction = value.split()
        numerator, denominator = fraction.split("/")
        if int(denominator) == 0:
            return None
        return Decimal(whole) + Decimal(numerator) / Decimal(denominator)
    if re.fullmatch(r"\d+/\d+", value):
        numerator, denominator = value.split("/")
        if int(denominator) == 0:
            return None
        return Decimal(numerator) / Decimal(denominator)
    number, _error = _normalise_number(value)
    return number


def _format_mm(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return format(rounded.normalize(), "f")


def interpret_dimension_text(text: str) -> dict[str, Any]:
    raw = text
    value = unicodedata.normalize("NFKC", text).strip()
    value = value.replace("′", "'").replace("’", "'").replace("″", '"').replace("“", '"').replace("”", '"')
    value = value.replace("⌀", "Ø").replace("ø", "Ø")
    value = re.sub(r"\s+", " ", value)
    dimension_type = "linear"
    prefix = re.match(r"^(Ø|R(?:ADIUS)?\b)\s*", value, re.IGNORECASE)
    if prefix:
        dimension_type = "diameter" if prefix.group(1).upper() == "Ø" else "radius"
        value = value[prefix.end():].strip()

    # Architectural feet-and-inches notation: 4'-6", 4 ft 6 in, 4' 6 1/2".
    feet_inches = re.fullmatch(
        r"""(?P<feet>\d+(?:\.\d+)?)\s*(?:ft|feet|foot|')
        (?:\s*(?:-\s*)?(?P<inches>\d+(?:\.\d+)?|\d+\s+\d+/\d+|\d+/\d+)\s*(?:in|inch(?:es)?|")?)?""",
        value,
        re.IGNORECASE,
    )
    if feet_inches:
        feet = Decimal(feet_inches.group("feet"))
        inches = _parse_fraction(feet_inches.group("inches") or "0")
        if inches is None or inches >= 12 or feet < 0 or (feet == 0 and inches <= 0):
            return _result(raw, "unrecognized", dimension_type, reason="The feet/inches components must describe a positive length.")
        millimetres = feet * UNIT_TO_MM["ft"] + inches * UNIT_TO_MM["in"]
        return _result(raw, "parsed", dimension_type, value_mm=_format_mm(millimetres), unit="ft/in")

    # Standalone fractional inches: 1/2", 2 1/2 in.
    fractional_inches = re.fullmatch(
        r"(?P<number>\d+\s+\d+/\d+|\d+/\d+)\s*(?:in|inch(?:es)?|\")",
        value,
        re.IGNORECASE,
    )
    if fractional_inches:
        number = _parse_fraction(fractional_inches.group("number"))
        millimetres = number * UNIT_TO_MM["in"]
        return _result(raw, "parsed", dimension_type, value_mm=_format_mm(millimetres), value=format(number.normalize(), "f"), unit="in")

    # Explicitly suffixed metric/imperial dimension.
    explicit = re.fullmatch(
        r"(?P<number>[+-]?[0-9][0-9., ]*)\s*(?P<unit>millimeters?|millimetres?|mm|centimeters?|centimetres?|cm|meters?|metres?|m|inches?|inch|in|feet|foot|ft)",
        value,
        re.IGNORECASE,
    )
    if explicit:
        number, error = _normalise_number(explicit.group("number"))
        if error:
            return _result(raw, "ambiguous" if "ambiguous" in error or "may be" in error else "unrecognized", dimension_type, reason=error)
        unit = UNIT_ALIASES[explicit.group("unit").lower()]
        if number <= 0:
            return _result(raw, "unrecognized", dimension_type, reason="A dimension length must be greater than zero.")
        millimetres = number * UNIT_TO_MM[unit]
        return _result(raw, "parsed", dimension_type, value_mm=_format_mm(millimetres), value=format(number.normalize(), "f"), unit=unit)

    # Bare number or fraction: deliberately do not assume millimetres.
    bare = _parse_fraction(value)
    if bare is not None:
        return _result(raw, "unit_missing", dimension_type, value=format(bare.normalize(), "f"), reason="A unit is not written; no conversion to millimetres was made.")
    if re.fullmatch(r"[+-]?[0-9][0-9., ]*", value):
        _number, error = _normalise_number(value)
        return _result(raw, "ambiguous" if error and ("ambiguous" in error or "may be" in error) else "unit_missing", dimension_type, reason=error or "A unit is not written; no conversion to millimetres was made.")
    return _result(raw, "unrecognized", dimension_type, reason="This text does not match a supported linear dimension format.")


def _result(
    raw: str,
    status: str,
    dimension_type: str,
    *,
    value_mm: str | None = None,
    value: str | None = None,
    unit: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "raw_text": raw,
        "status": status,
        "dimension_type": dimension_type,
        "value": value,
        "unit": unit,
        "value_mm": value_mm,
        "reason": reason,
        "requires_review": True,
    }
