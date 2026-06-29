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
        with patch.dict("os.environ", {}, clear=True), patch(
            "retail_store.cli.load_dotenv"
        ):
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
                "reset",
                "exit",
            ]
        )
        self.assertEqual(0, code)
        self.assertIn("Store data and session memory reset.", output)

    def test_instruction_without_api_key_reports_configuration_error(self) -> None:
        code, output = self.run_commands(["Sell one tote.", "quit"])
        self.assertEqual(0, code)
        self.assertTrue(any("OPENAI_API_KEY is required" in line for line in output))

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
