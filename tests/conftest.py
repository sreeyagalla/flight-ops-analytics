import subprocess
import sys

import duckdb
import pytest

from aeng import config, pipeline


@pytest.fixture(scope="session")
def raw_dir():
    if not (config.RAW_DIR / "flights.csv").exists():
        subprocess.check_call([sys.executable, str(config.ROOT / "scripts" / "fetch_data.py")])
    return config.RAW_DIR


@pytest.fixture(scope="session")
def built(raw_dir, tmp_path_factory):
    """Run the real pipeline into a throwaway DB; tests never touch the dev warehouse."""
    db = tmp_path_factory.mktemp("wh") / "test.duckdb"
    result = pipeline.run(raw_dir, db)
    return db, result


@pytest.fixture()
def con(built):
    c = duckdb.connect(str(built[0]), read_only=True)
    yield c
    c.close()
