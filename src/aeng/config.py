import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = Path(os.environ.get("AENG_RAW", ROOT / "data" / "raw"))
DB_PATH = Path(os.environ.get("AENG_DB", ROOT / "data" / "warehouse.duckdb"))
SQL_DIR = Path(__file__).parent / "sql"
RAW_TABLES = ["flights", "airlines", "airports", "weather", "planes"]
