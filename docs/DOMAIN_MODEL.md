# Retail Store Domain Model

## Purpose

This model converts the supplied flat CSV exports into a relational foundation for the Retail
Store Agent. It covers catalog, customers, suppliers, current inventory, historical sales,
returns, promotions, and purchase orders. Deterministic services operate on this model; the
language layer does not write tables directly.

The application clock is fixed at **2026-06-19**. “Last month” is **2026-05-01 through
2026-05-31**.

## Entities and relationships

- A **product** is a named product family such as Classic Tee.
- A **product variant** is a sellable unit identified by SKU. It belongs to one product and
  optionally has color and size attributes. Products without variant axes use `NULL` for both.
- Each variant has one current **inventory** record.
- A **supplier** can offer multiple products, and a product can be offered by multiple
  suppliers. `supplier_catalog` records the cost and lead time for that relationship.
- A **purchase order** records an order from one supplier for one product, including ordered
  and received quantities and lifecycle status. The table is empty at seed time and exists as
  a foundation for later restock and receiving workflows.
- An **order** optionally belongs to a customer; a missing customer represents a walk-in.
- An **order line** preserves the SKU, quantity, and unit price charged before the order-level
  discount. Prices are historical facts and are not derived from the current catalog.
- A **return** preserves the source CSV's SKU and references the exact original order line. The
  CSV's `(order_id, sku)` is resolved during import and must identify exactly one line; a
  composite foreign key guarantees the stored SKU matches that line's SKU.
- A **promotion** targets either a product or category over an inclusive date window.

## Representation choices

All monetary values are stored as integer cents to avoid binary floating-point errors. CSV
money is parsed with `Decimal`. Percentage values remain whole percentages, matching the
source exports.

Dates are stored as canonical ISO `YYYY-MM-DD` text, which preserves chronological ordering.
The loader strictly parses every date before insertion.

Promotion scope is polymorphic: `scope_ref` names either a `product_id` or a category depending
on `scope_type`. SQLite cannot express that conditional foreign key directly, so the loader
validates it before insertion.

## Integrity and seed behavior

The schema uses primary keys, foreign keys, unique constraints, enum checks, and numeric range
checks. The loader additionally validates CSV headers, complete inventory coverage, product
metadata consistency, relationships, return quantities, and refund calculations.

Seeding builds a temporary database and atomically replaces the destination only after all
validation, foreign-key checks, and SQLite integrity checks pass. The original CSV files remain
the immutable seed inputs.

The frozen business rules in `DATA_DICTIONARY.md` remain authoritative. They are implemented in
the deterministic service and analytics modules rather than delegated to an LLM.
