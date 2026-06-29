from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_store.database import connect
from retail_store.matching import SkuAmbiguityError, resolve_sku
from retail_store.seed import seed_database


class ProductMatchingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "retail.db"
        seed_database(ROOT / "data", self.database)
        self.connection = connect(self.database)

    def tearDown(self) -> None:
        self.connection.close()
        self.temp_dir.cleanup()

    def test_classic_tee_blue_medium_resolves(self) -> None:
        self.assertEqual(
            "TEE-BLU-M",
            resolve_sku(self.connection, "classic tee", color="blue", size="medium"),
        )

    def test_medium_hoodie_without_color_is_ambiguous(self) -> None:
        with self.assertRaisesRegex(
            SkuAmbiguityError, "HOOD-GRY-M.*HOOD-NVY-M"
        ):
            resolve_sku(self.connection, "medium hoodie")

    def test_canvas_tote_resolves_without_variant_axes(self) -> None:
        self.assertEqual("TOTE", resolve_sku(self.connection, "Canvas Tote"))


if __name__ == "__main__":
    unittest.main()

