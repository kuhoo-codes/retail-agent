from __future__ import annotations

import re
import sqlite3


class SkuResolutionError(ValueError):
    """Base class for deterministic SKU resolution failures."""


class SkuNotFoundError(SkuResolutionError):
    """Raised when no SKU satisfies the supplied description."""


class SkuAmbiguityError(SkuResolutionError):
    """Raised when a description does not identify exactly one SKU."""


PRODUCT_ALIASES = {
    "classic tee": "Classic Tee",
    "t shirt": "Classic Tee",
    "tees": "Classic Tee",
    "tee": "Classic Tee",
    "pullover hoodie": "Pullover Hoodie",
    "sweatshirt": "Pullover Hoodie",
    "hoodies": "Pullover Hoodie",
    "hoodie": "Pullover Hoodie",
    "canvas tote": "Canvas Tote",
    "totes": "Canvas Tote",
    "tote": "Canvas Tote",
    "bag": "Canvas Tote",
    "ceramic mug": "Ceramic Mug",
    "mugs": "Ceramic Mug",
    "mug": "Ceramic Mug",
    "wool socks": "Wool Socks",
    "socks": "Wool Socks",
    "sock": "Wool Socks",
}

SIZE_ALIASES = {
    "small": "S",
    "medium": "M",
    "med": "M",
    "large": "L",
    "s": "S",
    "m": "M",
    "l": "L",
}


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _alias_in_description(alias: str, description: str) -> bool:
    return f" {alias} " in f" {description} "


def _normalize_size(value: str) -> str:
    normalized = _normalize(value)
    try:
        return SIZE_ALIASES[normalized]
    except KeyError as exc:
        raise SkuNotFoundError(f"unknown size: {value!r}") from exc


def _description_size(description: str) -> str | None:
    words = description.split()
    matches = {SIZE_ALIASES[word] for word in words if word in SIZE_ALIASES}
    return next(iter(matches)) if len(matches) == 1 else None


def resolve_sku(
    connection: sqlite3.Connection,
    product_description: str,
    color: str | None = None,
    size: str | None = None,
) -> str:
    """Resolve a natural-language product description to exactly one SKU."""
    if not isinstance(product_description, str) or not product_description.strip():
        raise SkuNotFoundError("product description cannot be blank")

    description = _normalize(product_description)

    direct = connection.execute(
        "SELECT sku FROM product_variants WHERE lower(sku) = lower(?)",
        (product_description.strip(),),
    ).fetchall()
    if len(direct) == 1 and color is None and size is None:
        return direct[0]["sku"]

    product_name = next(
        (
            canonical
            for alias, canonical in sorted(
                PRODUCT_ALIASES.items(), key=lambda item: len(item[0]), reverse=True
            )
            if _alias_in_description(alias, description)
        ),
        None,
    )
    if product_name is None:
        exact_product = connection.execute(
            "SELECT name FROM products WHERE lower(name) = lower(?)",
            (product_description.strip(),),
        ).fetchone()
        product_name = exact_product["name"] if exact_product else None
    if product_name is None:
        raise SkuNotFoundError(f"no product found for {product_description!r}")

    rows = connection.execute(
        """SELECT pv.sku, pv.color, pv.size
           FROM product_variants AS pv
           JOIN products AS p ON p.product_id = pv.product_id
           WHERE lower(p.name) = lower(?)
           ORDER BY pv.sku""",
        (product_name,),
    ).fetchall()

    requested_size = _normalize_size(size) if size is not None else _description_size(description)
    if requested_size is not None:
        rows = [row for row in rows if row["size"] == requested_size]

    if color is not None:
        requested_color = color.strip().casefold()
        rows = [
            row
            for row in rows
            if row["color"] is not None and row["color"].casefold() == requested_color
        ]
    else:
        colors = {
            row["color"].casefold(): row["color"]
            for row in rows
            if row["color"] is not None
        }
        mentioned = [
            canonical
            for normalized, canonical in colors.items()
            if _alias_in_description(normalized, description)
        ]
        if len(mentioned) == 1:
            rows = [
                row
                for row in rows
                if row["color"] is not None
                and row["color"].casefold() == mentioned[0].casefold()
            ]

    if not rows:
        details = ", ".join(
            part
            for part in (
                product_description,
                f"color={color}" if color else None,
                f"size={size}" if size else None,
            )
            if part
        )
        raise SkuNotFoundError(f"no SKU found for {details}")
    if len(rows) > 1:
        skus = ", ".join(row["sku"] for row in rows)
        raise SkuAmbiguityError(
            f"product description is ambiguous; matching SKUs: {skus}"
        )
    return rows[0]["sku"]
