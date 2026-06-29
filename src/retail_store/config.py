from datetime import date
import os
from pathlib import Path

TODAY = date(2026, 6, 19)
LAST_MONTH_START = date(2026, 5, 1)
LAST_MONTH_END = date(2026, 5, 31)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "var" / "retail_store.db"


def load_dotenv(path: Path | None = None) -> None:
    """Load simple KEY=VALUE entries without overriding exported variables."""
    dotenv_path = path or PROJECT_ROOT / ".env"
    if not dotenv_path.is_file():
        return
    for line_number, raw_line in enumerate(
        dotenv_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"{dotenv_path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not key.replace("_", "a").isalnum() or key[0].isdigit():
            raise ValueError(f"{dotenv_path}:{line_number}: invalid variable name")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)
