from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_store.database import connect
from retail_store.seed import seed_database
from retail_store.services import receive_purchase_order, reorder_low_stock


class RestockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "retail.db"
        seed_database(ROOT / "data", self.database)
        self.connection = connect(self.database)

    def tearDown(self) -> None:
        self.connection.close()
        self.temp_dir.cleanup()

    def test_reorder_uses_lowest_cost_supplier_within_ten_days(self) -> None:
        purchase_orders = reorder_low_stock(self.connection)
        self.assertEqual(1, len(purchase_orders))
        purchase_order = purchase_orders[0]
        self.assertEqual("P-TOTE", purchase_order["product_id"])
        self.assertEqual("SUP-NW", purchase_order["supplier_id"])
        self.assertEqual("Northwind Supply", purchase_order["supplier_name"])
        self.assertEqual(50, purchase_order["quantity_ordered"])
        self.assertEqual("7.00", purchase_order["unit_cost"])
        self.assertLessEqual(purchase_order["lead_time_days"], 10)

        slow_cheaper = self.connection.execute(
            """SELECT unit_cost_cents, lead_time_days
               FROM supplier_catalog
               WHERE supplier_id = 'SUP-PG' AND product_id = 'P-TOTE'"""
        ).fetchone()
        self.assertEqual((650, 14), tuple(slow_cheaper))

    def test_receive_partial_tote_purchase_order(self) -> None:
        reorder_low_stock(self.connection)
        before = self.connection.execute(
            "SELECT on_hand_qty FROM inventory WHERE sku = 'TOTE'"
        ).fetchone()[0]

        result = receive_purchase_order(
            self.connection,
            "Canvas Totes",
            "Northwind",
            quantity_ordered=50,
            quantity_received=40,
        )
        self.assertEqual("PO-0001", result["po_id"])
        self.assertFalse(result["created_po"])
        self.assertEqual("partial", result["status"])
        self.assertEqual(40, result["quantity_received"])
        self.assertEqual(before + 40, result["remaining_inventory"])

        stored = self.connection.execute(
            """SELECT quantity_ordered, quantity_received, status
               FROM purchase_orders WHERE po_id = 'PO-0001'"""
        ).fetchone()
        self.assertEqual((50, 40, "partial"), tuple(stored))


if __name__ == "__main__":
    unittest.main()
