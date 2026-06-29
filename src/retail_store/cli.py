from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import Callable

from retail_store.agent import RetailAgent
from retail_store.config import DEFAULT_DATABASE_PATH, DEFAULT_DATA_DIR, load_dotenv
from retail_store.database import connect
from retail_store.seed import seed_database

WELCOME = "Retail Store Agent ready. Type an instruction, or 'exit' to quit."
HELP = (
    "Enter a retail instruction in plain language. Commands: "
    "help, reset, exit, quit."
)


def ensure_database(data_dir: Path, database_path: Path) -> None:
    if not database_path.is_file():
        seed_database(data_dir, database_path)


def run_cli(
    database_path: Path = DEFAULT_DATABASE_PATH,
    data_dir: Path = DEFAULT_DATA_DIR,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> int:
    load_dotenv()
    ensure_database(data_dir, database_path)
    connection = connect(database_path)
    agent = RetailAgent(connection)
    output_fn(WELCOME)

    try:
        while True:
            try:
                text = input_fn("> ")
            except EOFError:
                output_fn("Goodbye.")
                return 0
            except KeyboardInterrupt:
                output_fn("\nGoodbye.")
                return 0

            command = text.strip()
            if not command:
                continue
            if command.casefold() in {"exit", "quit"}:
                output_fn("Goodbye.")
                return 0
            if command.casefold() == "help":
                output_fn(HELP)
                continue
            if command.casefold() == "reset":
                connection.close()
                try:
                    seed_database(data_dir, database_path)
                    connection = connect(database_path)
                    agent = RetailAgent(connection)
                except Exception:
                    if os.getenv("DEBUG") == "1":
                        raise
                    output_fn("Unable to reset the store database.")
                    return 1
                output_fn("Store data and session memory reset.")
                continue

            try:
                output_fn(agent.handle_user_message(command))
            except sqlite3.Error as exc:
                if os.getenv("DEBUG") == "1":
                    raise
                output_fn(f"Database error: {exc}")
    finally:
        connection.close()


def main() -> None:
    try:
        code = run_cli()
    except Exception as exc:
        if os.getenv("DEBUG") == "1":
            raise
        print(f"Unable to start Retail Store Agent: {exc}", file=sys.stderr)
        code = 1
    raise SystemExit(code)
