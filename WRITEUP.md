# Retail Store Agent — Short Writeup

## Approach summary

The project uses a layered design: validated CSV seed data → normalized SQLite → deterministic
services and analytics → structured tools → agent and terminal UI. The optional LLM is limited
to mapping natural language to a tool and arguments. Store calculations and state changes always
run in Python services, and a deterministic parser provides an offline fallback.

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

Full schemas and defaults are in [docs/TOOLS.md](docs/TOOLS.md).

## Agent design

`RetailAgent` asks an isolated OpenAI-compatible client for at most a tool selection. If the API
key is absent, the provider fails, or the model chooses an unknown tool, the deterministic parser
is used. Tools return structured results; final receipts and reports are formatted locally.
Compound promotion-then-sale instructions execute as two ordered deterministic actions.

## Session memory

Session memory tracks recent turns plus the last order, return, purchase order, customer, items,
SKUs, and action. This supports references such as “that order,” “same customer,” “same item,”
and “now refund that.” Memory lasts for one CLI session and is cleared by `reset`.

## Business rules

Python services implement half-up per-unit order discounts, inclusive promotion windows,
lowest-price non-stacking promotions, original-paid-price refunds, good/damaged return inventory
behavior, eligible lowest-cost supplier selection (`lead_time_days <= 10`), Northwind cost
margin calculations, and May velocity/days-of-cover stockout rules. Mutations use transactions
or savepoints.

## Testing strategy

The suite covers seed validation, schema integrity, matching, pricing, orders, returns,
promotions, restocking, receiving, analytics, tools, memory, parser behavior, agent fallback,
CLI reset/error behavior, all ten public prompts end-to-end, and common hidden-prompt wording
variations.

## Known limitations and assumptions

- The assignment clock is fixed at 2026-06-19; “last month” means May 2026.
- The fallback parser intentionally supports common retail phrasing rather than unrestricted
  language understanding.
- Ambiguous product variants require clarification; the system does not guess a color or size.
- Multi-variant purchase-order receiving requires an SKU or enough color/size information.
- Session memory is in-process and is not persisted between program runs.

