"""Reproducible pipeline: raw CSV -> DuckDB raw_* -> staging -> marts -> data-quality checks.

Run:  python -m aeng.pipeline
Every run is recorded in pipeline_runs / dq_results so health is queryable and shown in the app.
"""
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from . import config
from .checks import run_checks


def _load_raw(con, raw_dir: Path) -> dict[str, int]:
    counts = {}
    for t in config.RAW_TABLES:
        path = (raw_dir / f"{t}.csv").as_posix()
        # 'rownames' is an R export artifact, dropped. 'NA' is the dataset's null marker.
        con.execute(f"CREATE OR REPLACE TABLE raw_{t} AS "
                    f"SELECT * EXCLUDE (rownames) FROM read_csv('{path}', header=true, "
                    f"nullstr=['NA',''], sample_size=-1)")
        counts[t] = con.execute(f"SELECT COUNT(*) FROM raw_{t}").fetchone()[0]
    return counts


def run(raw_dir: Path = None, db_path: Path = None) -> dict:
    raw_dir = Path(raw_dir or config.RAW_DIR)
    db_path = Path(db_path or config.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    con = duckdb.connect(str(db_path))
    counts = _load_raw(con, raw_dir)
    for sql_file in sorted(config.SQL_DIR.glob("*.sql")):
        con.execute(sql_file.read_text())
    results = run_checks(con)
    failed = [r for r in results if r["status"] == "fail"]
    run_row = {
        "run_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "duration_s": round(time.time() - started, 2),
        "flights_rows": counts["flights"],
        "checks_total": len(results),
        "checks_failed": len(failed),
        "checks_warned": sum(r["status"] == "warn" for r in results),
        "status": "failed" if failed else "ok",
    }
    con.execute("CREATE TABLE IF NOT EXISTS pipeline_runs (run_at VARCHAR, duration_s DOUBLE, "
                "flights_rows BIGINT, checks_total INT, checks_failed INT, checks_warned INT, status VARCHAR)")
    con.execute("INSERT INTO pipeline_runs VALUES (?,?,?,?,?,?,?)", list(run_row.values()))
    con.execute("CREATE OR REPLACE TABLE dq_results AS SELECT * FROM df", {"df": pd.DataFrame(results)}) \
        if False else None
    df = pd.DataFrame(results)  # noqa: F841  (referenced by DuckDB replacement scan)
    con.execute("CREATE OR REPLACE TABLE dq_results AS SELECT * FROM df")
    con.close()
    return {**run_row, "results": results}


def main() -> None:
    out = run()
    for r in out["results"]:
        print(f"[{r['status'].upper():4}] {r['check']:36} bad_rows={r['bad_rows']}")
    print(f"\nrun status={out['status']} rows={out['flights_rows']:,} in {out['duration_s']}s")
    sys.exit(1 if out["status"] == "failed" else 0)


if __name__ == "__main__":
    main()
