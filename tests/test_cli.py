from __future__ import annotations

import sys
import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_store.cli import run_cli
from retail_store.config import load_dotenv
from retail_store.database import connect


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "retail.db"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_commands(self, commands: list[str]) -> tuple[int, list[str]]:
        commands_iter = iter(commands)
        output: list[str] = []
        with patch.dict("os.environ", {}, clear=True):
            code = run_cli(
                database_path=self.database,
                data_dir=ROOT / "data",
                input_fn=lambda _prompt: next(commands_iter),
                output_fn=output.append,
            )
        return code, output

    def test_help_and_exit_seed_missing_database(self) -> None:
        code, output = self.run_commands(["help", "exit"])
        self.assertEqual(0, code)
        self.assertTrue(self.database.is_file())
        self.assertIn("Retail Store Agent ready", output[0])
        self.assertIn("help, reset, exit, quit", output[1])
        self.assertEqual("Goodbye.", output[-1])

    def test_reset_reseeds_database_and_clears_memory(self) -> None:
        code, output = self.run_commands(
            [
                "Ring up one Canvas Tote for a walk-in paying cash today.",
                "reset",
                "Ring up one Canvas Tote for a walk-in paying cash today.",
                "exit",
            ]
        )
        self.assertEqual(0, code)
        order_answers = [line for line in output if "Order O-1016 completed" in line]
        self.assertEqual(2, len(order_answers))
        self.assertIn("Store data and session memory reset.", output)

        connection = connect(self.database)
        try:
            self.assertEqual(
                16, connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            )
        finally:
            connection.close()

    def test_smoke_public_order_and_stockout_answers(self) -> None:
        code, output = self.run_commands(
            [
                "Ring up two Classic Tees, Blue Medium, and one Canvas Tote "
                "for a walk-in paying cash, dated today.",
                "What's about to stock out?",
                "exit",
            ]
        )
        self.assertEqual(0, code)
        self.assertTrue(any("Total paid: $68.00" in line for line in output))
        self.assertTrue(any("Stockout risk:" in line for line in output))

    def test_multi_item_refund_followup_requests_item(self) -> None:
        _code, output = self.run_commands(
            [
                "Ring up two Classic Tees, Blue Medium, and one Canvas Tote "
                "for a walk-in paying cash, dated today.",
                "now refund that",
                "quit",
            ]
        )
        self.assertIn(
            "I need the item or SKU to refund from order O-1016.", output
        )

    def test_keyboard_interrupt_exits_cleanly(self) -> None:
        output: list[str] = []

        def interrupt(_prompt: str) -> str:
            raise KeyboardInterrupt

        with patch.dict("os.environ", {}, clear=True):
            code = run_cli(
                database_path=self.database,
                data_dir=ROOT / "data",
                input_fn=interrupt,
                output_fn=output.append,
            )
        self.assertEqual(0, code)
        self.assertEqual("\nGoodbye.", output[-1])

    def test_dotenv_loads_values_without_overriding_exported_environment(self) -> None:
        dotenv = Path(self.temp_dir.name) / ".env"
        dotenv.write_text(
            "# local configuration\n"
            "OPENAI_API_KEY='from-file'\n"
            "RETAIL_AGENT_MODEL=gpt-test\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"OPENAI_API_KEY": "exported"}, clear=True):
            load_dotenv(dotenv)
            self.assertEqual("exported", os.environ["OPENAI_API_KEY"])
            self.assertEqual("gpt-test", os.environ["RETAIL_AGENT_MODEL"])


if __name__ == "__main__":
    unittest.main()
