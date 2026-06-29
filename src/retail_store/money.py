from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def cents_to_usd(cents: int) -> str:
    """Format an integer cent amount as USD without a currency symbol."""
    if isinstance(cents, bool) or not isinstance(cents, int):
        raise TypeError("cents must be an integer")
    return f"{Decimal(cents) / Decimal(100):.2f}"


def usd_to_cents(value: str | int | float | Decimal) -> int:
    """Convert a USD amount to cents using financial half-up rounding."""
    if isinstance(value, bool):
        raise TypeError("USD value must be numeric")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid USD amount: {value!r}") from exc
    if not amount.is_finite():
        raise ValueError(f"invalid USD amount: {value!r}")
    rounded = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(rounded * 100)


def apply_percent_discount_cents(
    unit_price_cents: int, discount_pct: int | float | Decimal
) -> int:
    """Apply a percentage discount and round the resulting unit price half-up."""
    if (
        isinstance(unit_price_cents, bool)
        or not isinstance(unit_price_cents, int)
        or unit_price_cents < 0
    ):
        raise ValueError("unit_price_cents must be a non-negative integer")
    if isinstance(discount_pct, bool):
        raise TypeError("discount_pct must be numeric")
    try:
        percentage = Decimal(str(discount_pct))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid discount percentage: {discount_pct!r}") from exc
    if not percentage.is_finite() or not Decimal(0) <= percentage <= Decimal(100):
        raise ValueError("discount_pct must be between 0 and 100")
    discounted = (
        Decimal(unit_price_cents)
        * (Decimal(100) - percentage)
        / Decimal(100)
    )
    return int(discounted.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

