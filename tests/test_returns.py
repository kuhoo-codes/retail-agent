from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_store.database import connect
from retail_store.seed import seed_database
from retail_store.services import ReturnError, process_return


class ReturnTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "retail.db"
        seed_database(ROOT / "data", self.database)
        self.connection = connect(self.database)

    def tearDown(self) -> None:
        self.connection.close()
        self.temp_dir.cleanup()

    def inventory(self, sku: str) -> int:
        return self.connection.execute(
            "SELECT on_hand_qty FROM inventory WHERE sku = ?", (sku,)
        ).fetchone()["on_hand_qty"]

    def test_good_hoodie_return_refunds_paid_price_and_restocks(self) -> None:
        before = self.inventory("HOOD-NVY-L")
        result = process_return(
            self.connection,
            "O-1006",
            product_description="hoodie",
            color="Navy",
            size="Large",
            condition="good",
        )
        self.assertEqual("R-2002", result["return_id"])
        self.assertEqual("HOOD-NVY-L", result["sku"])
        self.assertEqual(1, result["order_line_no"])
        self.assertEqual("54.00", result["refund_amount"])
        self.assertEqual(1, result["inventory_increase"])
        self.assertEqual(before + 1, self.inventory("HOOD-NVY-L"))

    def test_damaged_tote_return_does_not_restock(self) -> None:
        before = self.inventory("TOTE")
        result = process_return(
            self.connection,
            "O-1006",
            product_description="Canvas Tote",
            condition="damaged",
        )
        self.assertEqual("16.20", result["refund_amount"])
        self.assertEqual(0, result["inventory_increase"])
        self.assertEqual(before, self.inventory("TOTE"))

    def test_returning_more_than_remaining_sold_quantity_is_rejected(self) -> None:
        before_count = self.connection.execute(
            "SELECT COUNT(*) FROM returns"
        ).fetchone()[0]
        with self.assertRaisesRegex(ReturnError, "available 1"):
            process_return(
                self.connection,
                "O-1006",
                sku="HOOD-NVY-L",
                quantity=2,
            )
        self.assertEqual(
            before_count,
            self.connection.execute("SELECT COUNT(*) FROM returns").fetchone()[0],
        )


if __name__ == "__main__":
    unittest.main()

