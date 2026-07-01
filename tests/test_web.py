from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_store.web import STATIC_DIR, WebSession


class WebSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "retail.db"
        self.env_patch = patch.dict(os.environ, {}, clear=True)
        self.env_patch.start()
        self.session = WebSession(self.database, ROOT / "data")

    def tearDown(self) -> None:
        self.session.close()
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def test_prompt_uses_same_agent_and_session_memory_as_cli(self) -> None:
        sale = self.session.execute(
            "Ring up one Navy Medium hoodie for Sarah Chen."
        )
        returned = self.session.execute("now refund that")
        self.assertTrue(sale["ok"])
        self.assertIn("O-1016", sale["output"])
        self.assertTrue(returned["ok"])
        self.assertIn("Return R-2002", returned["output"])

    def test_help_reset_and_exit_match_cli_commands(self) -> None:
        self.assertIn("help, reset, exit, quit", self.session.execute("help")["output"])
        self.assertIn("session memory reset", self.session.execute("reset")["output"])
        self.assertTrue(self.session.execute("exit")["exit"])

    def test_analytics_response_is_deterministic(self) -> None:
        result = self.session.execute("How much did Sarah Chen spend last month?")
        self.assertTrue(result["ok"])
        self.assertIn("$410.20", result["output"])

    def test_static_terminal_assets_exist(self) -> None:
        for filename in ("index.html", "terminal.css", "terminal.js"):
            self.assertTrue((STATIC_DIR / filename).is_file())


if __name__ == "__main__":
    unittest.main()
