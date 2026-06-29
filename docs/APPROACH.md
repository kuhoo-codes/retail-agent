# Implementation Approach

## Architecture

The application is intentionally layered so language interpretation cannot bypass store rules:

1. CSV exports are validated and atomically seeded into a normalized SQLite database.
2. `services.py`, `analytics.py`, `matching.py`, and `money.py` implement all deterministic
   store behavior and calculations.
3. `tools.py` exposes structured actions and converts expected failures into safe results.
4. `RetailAgent` uses an optional LLM only to select a tool and its arguments. Without an API
   key—or if the provider fails—the deterministic intent parser handles common phrasing.
5. Tool results are formatted locally, and the terminal loop retains session memory for
   follow-up references.

Money is represented as integer cents. Percentage discounts round each unit half-up. Mutating
operations use SQLite transactions or savepoints, so failed multi-line operations roll back.

## Tool catalog

| Tool | Required parameters | Purpose |
|---|---|---|
| `ring_up_order` | `items` | Resolve products, price a sale, check/decrement inventory, and create an order. |
| `process_return` | `order_id` plus an item reference | Refund the original paid price and restock only good returns. |
| `create_promotion` | description, percent, scope, start/end dates | Create an inclusive product/category promotion window. |
| `reorder_low_stock` | none | Reorder inventory at/below its threshold from the eligible lowest-cost supplier. |
| `receive_purchase_order` | product, supplier, ordered/received quantities | Create/find a PO, receive stock, and update PO status. |
| `top_products_by_profit_margin` | none | Rank period product margins using paid revenue, refunds, and Northwind costs. |
| `get_stockout_risk` | none | Report reorder-threshold and days-of-cover risks from May velocity. |

Complete JSON-schema-like parameter definitions and descriptions live in `tools.py`.

## Reliability choices

- Historical order-line prices are immutable; promotions affect only new sales.
- Returns reference the exact original order line and preserve the SKU.
- Current stock mutations, returns, purchase orders, and sales are transactional.
- SQLite foreign keys and integrity checks are enabled.
- The assignment clock is fixed at 2026-06-19; “last month” is May 2026.
- Public prompt behavior is covered at service, parser, agent, and CLI levels.

