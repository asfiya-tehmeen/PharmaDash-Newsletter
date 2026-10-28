"""All arithmetic happens here, in code, never in the model's head."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def _d(x) -> Decimal:
    return Decimal(str(x))


def pct_change(old, new, places: int = 1) -> float:
    """Percent change from old to new, rounded half-up. Raises on old == 0."""
    old, new = _d(old), _d(new)
    if old == 0:
        raise ZeroDivisionError("percent change from zero is undefined")
    return float(((new - old) / abs(old) * 100).quantize(Decimal(10) ** -places, ROUND_HALF_UP))


def cagr(start, end, years: float, places: int = 1) -> float:
    if years <= 0 or _d(start) <= 0 or _d(end) <= 0:
        raise ValueError("CAGR needs positive values and a positive number of years")
    return round(((float(end) / float(start)) ** (1 / years) - 1) * 100, places)


def total(values: list) -> float:
    return float(sum((_d(v) for v in values), Decimal(0)))


def share(part, whole, places: int = 1) -> float:
    return float((_d(part) / _d(whole) * 100).quantize(Decimal(10) ** -places, ROUND_HALF_UP))


def human_money(value: float, currency: str = "USD") -> str:
    """12_345_000_000 -> '$12.3 billion' (USD) or '12.3 billion DKK'."""
    v = abs(value)
    for div, word in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if v >= div:
            num = f"{value / div:.1f}".rstrip("0").rstrip(".")
            return f"${num} {word}" if currency == "USD" else f"{num} {word} {currency}"
    return f"${value:,.0f}" if currency == "USD" else f"{value:,.0f} {currency}"
