from __future__ import annotations

import re
from typing import Any

from retail_store.memory import SessionMemory

TODAY = "2026-06-19"
LAST_MONTH_START = "2026-05-01"
LAST_MONTH_END = "2026-05-31"

NUMBER_WORDS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

PRODUCT_PATTERNS = (
    (
        r"\bclassic\s+tees?\b|\bt-?shirts?\b|\btees?\b",
        "Classic Tee",
        "P-TEE",
    ),
    (r"\bhoodies?\b|\bsweatshirts?\b", "hoodie", "P-HOOD"),
    (r"\bcanvas\s+totes?\b|\btotes?\b|\bbags?\b", "Canvas Tote", "P-TOTE"),
    (r"\b(?:ceramic\s+)?mugs?\b", "Mug", "P-MUG"),
    (r"\b(?:wool\s+)?socks?\b", "Socks", "P-SOCK"),
)

COLORS = {
    "blue": "Blue",
    "black": "Black",
    "gray": "Gray",
    "grey": "Gray",
    "navy": "Navy",
}

SIZES = {
    "small": "S",
    "medium": "M",
    "med": "M",
    "large": "L",
    "s": "S",
    "m": "M",
    "l": "L",
}


def _result(
    tool_name: str | None,
    arguments: dict[str, Any],
    confidence: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "arguments": arguments,
        "confidence": confidence,
        "reason": reason,
    }


def _number(value: str) -> int:
    return int(value) if value.isdigit() else NUMBER_WORDS[value.casefold()]


def _date_from_text(text: str, *, default: str = TODAY) -> str:
    explicit = re.search(r"\b20\d{2}-\d{2}-\d{2}\b", text)
    if explicit:
        return explicit.group(0)
    if "today" in text.casefold():
        return TODAY
    return default


def _variant_details(text: str) -> dict[str, str]:
    lowered = text.casefold()
    details: dict[str, str] = {}
    for token, canonical in COLORS.items():
        if re.search(rf"\b{token}\b", lowered):
            details["color"] = canonical
            break
    for token, canonical in SIZES.items():
        if re.search(rf"\b{token}\b", lowered):
            details["size"] = canonical
            break
    return details


def _product_matches(text: str) -> list[tuple[re.Match[str], str, str]]:
    matches: list[tuple[re.Match[str], str, str]] = []
    for pattern, description, product_id in PRODUCT_PATTERNS:
        matches.extend(
            (match, description, product_id)
            for match in re.finditer(pattern, text, flags=re.IGNORECASE)
        )
    matches.sort(key=lambda entry: entry[0].start())
    return matches


def _parse_items(text: str, memory: SessionMemory) -> list[dict[str, Any]]:
    if "same item" in text.casefold():
        remembered = memory.get("last_items", [])
        return remembered if isinstance(remembered, list) else []

    matches = _product_matches(text)
    items: list[dict[str, Any]] = []
    previous_end = 0
    for index, (match, description, _product_id) in enumerate(matches):
        before = text[previous_end : match.start()]
        quantity_matches = list(
            re.finditer(
                r"\b(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten)\b",
                before,
                flags=re.IGNORECASE,
            )
        )
        quantity = _number(quantity_matches[-1].group(1)) if quantity_matches else 1
        next_start = matches[index + 1][0].start() if index + 1 < len(matches) else len(text)
        context_start = (
            previous_end + quantity_matches[-1].start()
            if quantity_matches
            else previous_end
        )
        context = text[context_start:next_start]
        item: dict[str, Any] = {
            "product_description": description,
            "quantity": quantity,
        }
        item.update(_variant_details(context))
        items.append(item)
        previous_end = match.end()
    return items


def _customer_from_text(text: str, memory: SessionMemory) -> str | None:
    lowered = text.casefold()
    if (
        "walk-in" in lowered
        or "walk in" in lowered
        or "walkin" in lowered
        or "no customer" in lowered
    ):
        return None
    if "same customer" in lowered:
        return memory.get("last_customer_name")
    match = re.search(
        r"\bfor\s+([A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+)+)",
        text,
    )
    if match:
        name = re.split(
            r"\s+(?:paying|dated|on)\b", match.group(1), maxsplit=1
        )[0]
        return name.strip()
    return None


def _parse_return(text: str, memory: SessionMemory) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "quantity": 1,
        "condition": (
            "damaged"
            if re.search(r"\bdamaged\b|came back damaged", text, re.IGNORECASE)
            else "good"
        ),
        "return_date": _date_from_text(text),
    }
    order_match = re.search(r"\bO-\d+\b", text, re.IGNORECASE)
    if order_match:
        arguments["order_id"] = order_match.group(0).upper()
    elif memory.resolve_reference(text):
        arguments["order_id"] = memory.get("last_order_id")

    product_matches = _product_matches(text)
    if product_matches:
        arguments["product_description"] = product_matches[0][1]
        arguments.update(_variant_details(text))
    elif len(memory.get("last_skus", [])) == 1:
        arguments["sku"] = memory.get("last_skus")[0]

    quantity_match = re.search(
        r"(?<!-)\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b(?!-)",
        text,
        re.IGNORECASE,
    )
    if quantity_match:
        arguments["quantity"] = _number(quantity_match.group(1))
    return arguments


def parse_intent_without_llm(
    user_text: str, memory: SessionMemory
) -> dict[str, Any]:
    """Map common retail phrasing to one existing deterministic tool."""
    if not isinstance(user_text, str) or not user_text.strip():
        return _result(
            None, {}, "low", "Please provide a retail operation or question."
        )
    text = user_text.strip()
    lowered = text.casefold()

    if re.search(
        r"about to stock out|stockout|stock out|stock-out|low inventory",
        lowered,
    ):
        return _result(
            "get_stockout_risk",
            {},
            "high",
            "Matched the stockout-risk analytics request.",
        )

    if (
        re.search(r"\bprofit\b|\bmargin\b", lowered)
        and re.search(r"\btop\b|\bbest\b", lowered)
    ):
        limit_match = re.search(r"\btop\s+(\d+|five)\b", lowered)
        limit = _number(limit_match.group(1)) if limit_match else 5
        return _result(
            "top_products_by_profit_margin",
            {
                "start_date": LAST_MONTH_START,
                "end_date": LAST_MONTH_END,
                "limit": limit,
            },
            "high",
            "Matched profit-margin analytics for last month.",
        )

    if re.search(r"\breorder\b|\brestock\b", lowered) and (
        "below" in lowered
        or "reorder point" in lowered
        or "low stock" in lowered
        or "restock" in lowered
    ):
        return _result(
            "reorder_low_stock",
            {"created_date": _date_from_text(text)},
            "high",
            "Matched the below-reorder-point workflow.",
        )

    if (
        ("purchase order" in lowered or re.search(r"\bpo\b", lowered))
        and re.search(r"\breceive|arrived|delivered\b", lowered)
    ):
        products = _product_matches(text)
        ordered = re.search(
            r"(?:for|ordered)\s+(\d+)", lowered
        )
        arrived = re.search(r"(\d+)\s+(?:arrived|received|delivered)", lowered)
        supplier = re.search(
            r"\bfrom\s+([A-Za-z][A-Za-z ]+?)(?=\s+is\b|\s+was\b|\s+and\b|,|$)",
            text,
            re.IGNORECASE,
        )
        if products and ordered and arrived and supplier:
            arguments = {
                "product_description": products[0][1],
                "supplier_name": supplier.group(1).strip(),
                "quantity_ordered": int(ordered.group(1)),
                "quantity_received": int(arrived.group(1)),
                "received_date": _date_from_text(text),
            }
            arguments.update(_variant_details(text))
            return _result(
                "receive_purchase_order",
                arguments,
                "high",
                "Matched purchase-order receiving quantities and supplier.",
            )
        return _result(
            None,
            {},
            "low",
            "Please specify the product, supplier, ordered quantity, and received quantity.",
        )

    if re.search(r"\bput\b.*\bpercent off\b|\b\d+\s*%\s*off\b", lowered):
        percent = re.search(r"(\d+)\s*(?:%|percent)\s*off", lowered)
        dates = re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", text)
        products = _product_matches(text)
        if percent and len(dates) >= 2 and products:
            product_description, product_id = products[0][1], products[0][2]
            return _result(
                "create_promotion",
                {
                    "description": (
                        f"{product_description} {int(percent.group(1))}% off"
                    ),
                    "percent_off": int(percent.group(1)),
                    "scope_type": "product",
                    "scope_ref": product_id,
                    "start_date": dates[0],
                    "end_date": dates[1],
                },
                "high",
                "Matched a dated product promotion.",
            )
        return _result(
            None,
            {},
            "low",
            "Please specify the product, percent off, start date, and end date.",
        )

    if re.search(
        r"\breturn(?:s|ed|ing)?\b|\brefund(?:s|ed|ing)?\b|\bcame back\b",
        lowered,
    ):
        arguments = _parse_return(text, memory)
        if "order_id" not in arguments:
            return _result(
                None,
                {},
                "low",
                "Which order should be returned or refunded?",
            )
        return _result(
            "process_return",
            arguments,
            "high" if "sku" in arguments or "product_description" in arguments else "medium",
            "Matched a return/refund request and resolved the original order.",
        )

    if re.search(r"\bring up\b|\bsell\b|\bcheckout\b|\bbuy\b", lowered):
        items = _parse_items(text, memory)
        if not items:
            return _result(
                None,
                {},
                "low",
                "Please specify which item and quantity to sell.",
            )
        payment_method = (
            "cash" if re.search(r"\bcash\b", lowered) else "card"
        )
        return _result(
            "ring_up_order",
            {
                "items": items,
                "customer_name": _customer_from_text(text, memory),
                "payment_method": payment_method,
                "order_date": _date_from_text(text),
                "order_discount_pct": 0,
            },
            "high",
            "Matched a sale and extracted its products, variants, and payment details.",
        )

    return _result(
        None,
        {},
        "low",
        "I could not determine the retail action. Please clarify what you want to do.",
    )
