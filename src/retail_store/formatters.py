from __future__ import annotations

from typing import Any


LABELS = {
    "product": "Product",
    "product_id": "Product ID",
    "product_name": "Product",
    "category": "Category",
    "sku": "SKU",
    "variant": "Variant",
    "color": "Color",
    "size": "Size",
    "customer": "Customer",
    "customer_id": "Customer ID",
    "customer_name": "Customer",
    "customer_type": "Customer Type",
    "payment_method": "Payment Method",
    "date": "Date",
    "month": "Month",
    "order_id": "Order ID",
    "revenue_gross": "Gross Revenue",
    "revenue_net": "Net Revenue",
    "units_sold": "Units Sold",
    "units_kept": "Units Kept",
    "refunds": "Refunds",
    "refund_quantity": "Refund Quantity",
    "cost": "Cost",
    "margin": "Margin",
    "order_count": "Order Count",
    "avg_order_value": "Average Order Value",
}
MONEY_FIELDS = {
    "revenue_gross",
    "revenue_net",
    "refunds",
    "cost",
    "margin",
    "avg_order_value",
}


def format_store_metrics(result: dict[str, Any]) -> str:
    """Render composable query results as a compact deterministic table."""
    metrics = result["metrics"]
    dimensions = result["group_by"]
    fields = [*dimensions, *metrics]
    dates = result.get("date_range")
    grouping = ", ".join(LABELS.get(item, item) for item in dimensions)
    title = f"Store metrics by {grouping}" if grouping else "Store metrics"
    if dates:
        title += f" for {dates['start_date']} to {dates['end_date']}"
    title += ":"
    if not result["rows"]:
        return title + "\n\nNo matching sales or returns."

    lines = [
        title,
        "",
        "| " + " | ".join(LABELS.get(field, field) for field in fields) + " |",
        "| " + " | ".join("---" for _ in fields) + " |",
    ]
    for row in result["rows"]:
        values = []
        for field in fields:
            value = row.get(field)
            if field in MONEY_FIELDS:
                value = f"${value}"
            elif value is None:
                value = "—"
            values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def format_tool_result(tool_name: str, data: Any) -> str:
    """Format offline tool results without deriving or inventing values."""
    if tool_name == "ring_up_order":
        lines = "; ".join(
            f"{line['quantity']} × {line['name']} ({line['sku']}) at ${line['unit_price']}"
            for line in data["line_items"]
        )
        return (
            f"Order {data['order_id']} completed for {data['customer_id']}: "
            f"{lines}. Total paid: ${data['total_paid']}."
        )
    if tool_name == "process_return":
        return (
            f"Return {data['return_id']} processed for {data['sku']}. "
            f"Refund: ${data['refund_amount']}. "
            f"Inventory increased by {data['inventory_increase']}."
        )
    if tool_name == "create_promotion":
        return (
            f"Promotion {data['promo_id']} created: {data['percent_off']}% off "
            f"{data['scope_ref']} from {data['start_date']} through {data['end_date']}."
        )
    if tool_name == "reorder_low_stock":
        if not data:
            return "No eligible low-stock items required a new purchase order."
        items = "; ".join(
            f"{row['po_id']}: {row['quantity_ordered']} units of {row['product_id']} "
            f"from {row['supplier_name']} ({row['lead_time_days']} day lead time)"
            for row in data
        )
        return f"Created {len(data)} purchase order(s): {items}."
    if tool_name == "receive_purchase_order":
        return (
            f"Purchase order {data['po_id']} received {data['quantity_received']} "
            f"of {data['quantity_ordered']} units; status: {data['status']}. "
            f"Remaining inventory: {data['remaining_inventory']}."
        )
    if tool_name == "top_products_by_profit_margin":
        items = "; ".join(
            f"{index}. {row['product_name']} — margin ${row['margin']}"
            for index, row in enumerate(data, start=1)
        )
        return f"Top products by profit margin: {items}."
    if tool_name == "get_stockout_risk":
        if not data:
            return "No products are currently at stockout risk."
        items = "; ".join(
            f"{row['product_name']} ({row['on_hand_total']} on hand, "
            f"{row['days_of_cover']} days of cover; {', '.join(row['reasons'])})"
            for row in data
        )
        return f"Stockout risk: {items}."
    return f"{tool_name} completed."
