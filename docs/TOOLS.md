# Tool/action reference

All tools return a `ToolResult` with `ok`, structured `data`, an optional `error`, and
`session_updates`. Expected input and domain failures are returned as `ok=false` instead of
escaping into the agent loop.

## `ring_up_order`

Creates an order, checks/decrements inventory, and stores promotion-adjusted line prices before
any order-level discount.

- Required: `items` — list of `{product_description, quantity, color?, size?}`
- Optional: `customer_name`, `payment_method` (`cash` or `card`, default `card`)
- Optional: `order_date` (default `2026-06-19`), `order_discount_pct` (default `0`)

## `process_return`

Returns units against the original order line and refunds the price actually paid.

- Required: `order_id`
- Item reference: `product_description` or `sku`; optional `color` and `size`
- Optional: `quantity` (default `1`), `condition` (`good` or `damaged`, default `good`)
- Optional: `return_date` (default `2026-06-19`)

## `create_promotion`

Creates a percentage promotion with an inclusive date window.

- Required: `description`, `percent_off`
- Required: `scope_type` (`product` or `category`) and valid `scope_ref`
- Required: `start_date`, `end_date`

## `reorder_low_stock`

Creates purchase orders for SKUs at or below their reorder points, grouped by product.

- Optional: `created_date` (default `2026-06-19`)

## `receive_purchase_order`

Receives a shipment against an open/partial PO, creating the stated PO when absent.

- Required: `product_description`, `supplier_name`
- Required: `quantity_ordered`, `quantity_received`
- Optional: `received_date` (default `2026-06-19`)
- Optional variant selection: `sku`, `color`, `size`

## `top_products_by_profit_margin`

Ranks products by deterministic margin using paid revenue, period refunds, retained units, and
Northwind Supply costs.

- Optional: `start_date` (default `2026-05-01`)
- Optional: `end_date` (default `2026-05-31`)
- Optional: `limit` (default `5`)

## `get_stockout_risk`

Returns products at/below a reorder point or below 14 days of cover using May sales velocity.
Results include the specific SKUs at or below their reorder points.

- Parameters: none

## `inventory_report`

Reports inventory by SKU, including product totals, reorder points, reorder quantities, and days
of cover.

- Optional: `product_description` or exact `sku`

## `order_details`

Reads an order without mutating it, including customer, date, payment method, paid unit prices,
quantities, SKUs, and total paid.

- Required: `order_id`

## `sales_report`

Reports units sold, gross revenue, returned units, refunds, net revenue, COGS, and margin.

- Optional: `start_date`, `end_date`, `product_description`
- Optional: `group_by` (`product` or `category`)
- Optional: `only_with_refunds`, `only_with_returns`

## `recommend_supplier`

Ranks supplier offers for a product by unit cost and then lead time. It is read-only.

- Required: `product_description`

## `cancel_purchase_order`

Cancels an open or partially received purchase order.

- Required: `po_id`

## `price_quote`

Returns the effective promotion-aware unit price without creating an order.

- Required: `product_description`
- Optional: `price_date`, `color`, `size`

## `purchase_order_report`

Reports supplier, quantities, receipt status, creation date, and lead time. It is read-only.

- Parameters: none
