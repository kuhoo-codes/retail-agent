from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_store.web import WebSession, create_handler


session = WebSession(
    database_path=Path("/tmp/retail_store.db"),
    data_dir=ROOT / "data",
)
handler = create_handler(session)
