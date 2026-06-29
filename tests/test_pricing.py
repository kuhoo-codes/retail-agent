from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_store.database import connect
from retail_store.money import (
    apply_percent_discount_cents,
    cents_to_usd,
    usd_to_cents,
)
from retail_store.seed import seed_database
from retail_store.services import (
    get_active_promotions,
    get_effective_unit_price_cents,
)


class PricingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "retail.db"
        seed_database(ROOT / "data", self.database)
        self.connection = connect(self.database)

    def tearDown(self) -> None:
        self.connection.close()
        self.temp_dir.cleanup()

    def test_money_conversion_helpers(self) -> None:
        self.assertEqual("25.00", cents_to_usd(2500))
        self.assertEqual(2500, usd_to_cents("25.00"))

    def test_order_discount_rounds_each_unit_half_up(self) -> None:
        self.assertEqual(1, apply_percent_discount_cents(1, 50))
        self.assertEqual(54_00, apply_percent_discount_cents(60_00, 10))

    def test_active_promotion_window_is_inclusive(self) -> None:
        self.assertEqual(
            ["PR-001"],
            [
                promotion.promo_id
                for promotion in get_active_promotions(
                    self.connection, "TEE-BLU-M", "2026-05-01"
                )
            ],
        )
        self.assertEqual(
            20_00,
            get_effective_unit_price_cents(
                self.connection, "TEE-BLU-M", "2026-05-07"
            ),
        )
        self.assertEqual(
            25_00,
            get_effective_unit_price_cents(
                self.connection, "TEE-BLU-M", "2026-05-08"
            ),
        )

    def test_best_promotion_wins_without_stacking(self) -> None:
        self.connection.execute(
            """INSERT INTO promotions
               (promo_id, description, type, value_pct, scope_type, scope_ref,
                start_date, end_date)
               VALUES ('PR-002', 'Apparel 30% off', 'percent_off', 30,
                       'category', 'apparel', '2026-05-01', '2026-05-31')"""
        )
        self.assertEqual(
            17_50,
            get_effective_unit_price_cents(
                self.connection, "TEE-BLU-M", "2026-05-02"
            ),
        )


if __name__ == "__main__":
    unittest.main()
