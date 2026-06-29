# Retail Store Agent — Short Writeup

## Approach summary

The project uses a layered design: validated CSV seed data → normalized SQLite → deterministic
services and analytics → structured tools → model-driven agent and terminal UI. The model
interprets language and can execute multiple tools iteratively. Store calculations and state
changes always run in Python services.

## Domain model

Products are separated from sellable SKU variants so apparel variants and single-SKU goods use
the same model. Inventory belongs to SKUs; supplier offers belong to products. Orders preserve
historical line prices, and returns reference the exact original order line while preserving the
returned SKU. Promotions target a product or category. Purchase orders track ordered/received
quantities and status. Money is stored as integer cents and dates as validated ISO text.

See [docs/DOMAIN_MODEL.md](docs/DOMAIN_MODEL.md) for details.

## Tool/action layer

| Tool | Purpose | Parameters |
|---|---|---|
| `ring_up_order` | Create a priced sale and decrement stock. | `items`; optional `customer_name`, `payment_method`, `order_date`, `order_discount_pct` |
| `process_return` | Refund original paid price and conditionally restock. | `order_id`; item via `product_description` or `sku`; optional `color`, `size`, `quantity`, `condition`, `return_date` |
| `create_promotion` | Create an inclusive product/category discount window. | `description`, `percent_off`, `scope_type`, `scope_ref`, `start_date`, `end_date` |
| `reorder_low_stock` | Create POs for inventory at/below reorder points. | optional `created_date` |
| `receive_purchase_order` | Find/create a PO, receive inventory, update status. | product, supplier, ordered/received quantities; optional date and SKU variant |
| `top_products_by_profit_margin` | Rank products by period margin. | optional `start_date`, `end_date`, `limit` |
| `get_stockout_risk` | Report reorder and days-of-cover risks. | none |
| `inventory_report` | Show on-hand quantity, reorder point, and days of cover by SKU. | optional product or SKU |
| `order_details` | Show customer, payment, lines, paid unit prices, and total. | `order_id` |
| `sales_report` | Report units, revenue, returns, refunds, COGS, and margin. | optional period, product, grouping, and filters |
| `recommend_supplier` | Rank supplier offers by cost and lead time. | product |
| `cancel_purchase_order` | Cancel an open or partially received PO. | `po_id` |
| `price_quote` | Quote a promotion-aware price without creating an order. | product; optional variant and date |

Full schemas and defaults are in [docs/TOOLS.md](docs/TOOLS.md).

## Agent design

`RetailAgent` runs an iterative OpenAI-compatible tool-calling loop. Each tool result—including
domain errors—is sent back to the model, which can clarify the request, call another tool, or
produce the final response. Unknown tools are rejected by the agent. There is no regex intent
router or offline natural-language fallback.

## Session memory

Session memory tracks recent turns plus the last order, return, purchase order, customer, items,
SKUs, and action. This supports references such as “that order,” “same customer,” “same item,”
“now refund that,” “last order,” and “last purchase order.” Memory lasts for one CLI session
and is cleared by `reset`.

## Business rules

Python services implement half-up per-unit order discounts, inclusive promotion windows,
lowest-price non-stacking promotions, original-paid-price refunds, good/damaged return inventory
behavior, eligible lowest-cost supplier selection (`lead_time_days <= 10`), Northwind cost
margin calculations, and May velocity/days-of-cover stockout rules. Mutations use transactions
or savepoints.

## Testing strategy

The offline suite covers seed validation, schema integrity, matching, pricing, orders, returns,
promotions, restocking, receiving, analytics, tools, memory, the iterative agent/tool boundary,
and CLI configuration/reset behavior. Agent tests use scripted model clients and do not make
network calls.

## Known limitations and assumptions

- The assignment clock is fixed at 2026-06-19; “last month” means May 2026.
- Natural-language operation requires a configured OpenAI-compatible model.
- Ambiguous product variants require clarification; the system does not guess a color or size.
- Multi-variant purchase-order receiving requires an SKU or enough color/size information.
- Session memory is in-process and is not persisted between program runs.
