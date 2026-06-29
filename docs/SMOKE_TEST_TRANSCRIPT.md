# Evaluator Smoke Test Transcript

This transcript was captured from the real CLI with `OPENAI_API_KEY` unset. The database was
reset immediately before the session:

```sh
PYTHONPATH=src python3 -m retail_store.seed
```

The app was started with the evaluator command:

```sh
PYTHONPATH=src python3 -m retail_store
```

Representative session:

```text
Retail Store Agent ready. Type an instruction, or 'exit' to quit.

> Ring up two Classic Tees, Blue Medium, and one Canvas Tote for a walk-in paying cash, dated today.
Order O-1016 completed for walk-in: 2 × Classic Tee (TEE-BLU-M) at $25.00; 1 × Canvas Tote (TOTE) at $18.00. Total paid: $68.00.

> Ring up a hoodie in medium for Sarah Chen.
I need clarification: product description is ambiguous; matching SKUs: HOOD-GRY-M, HOOD-NVY-M

> Put all hoodies on 20% off from 2026-06-20 to 2026-06-22, then ring up one Gray Medium hoodie dated 2026-06-21 and tell me the price.
Promotion PR-002 created: 20% off product P-HOOD from 2026-06-20 through 2026-06-22. Order O-1017 completed for walk-in: 1 × Pullover Hoodie (HOOD-GRY-M) at $48.00. Total paid: $48.00.

> Reorder anything that's below its reorder point, from the best supplier. Date it today.
Created 1 purchase order(s): PO-0001: 50 units of P-TOTE from Northwind Supply.

> What were my top five products by profit margin last month?
Top products by profit margin: 1. Classic Tee — margin $420.00; 2. Pullover Hoodie — margin $282.00; 3. Wool Socks — margin $120.00; 4. Canvas Tote — margin $108.20; 5. Ceramic Mug — margin $70.00.

> What's about to stock out?
Stockout risk: Canvas Tote (3 on hand, 9.0 days of cover; at_or_below_reorder_point, fewer_than_14_days_of_cover).

> exit
Goodbye.
```

The session completed without a stack trace.
