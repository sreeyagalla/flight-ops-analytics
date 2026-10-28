import shutil

import pandas as pd

from aeng import pipeline


def test_row_counts_match_source_csvs(built, con, raw_dir):
    flights = pd.read_csv(raw_dir / "flights.csv", usecols=["year"])
    assert con.execute("SELECT COUNT(*) FROM fct_flights").fetchone()[0] == len(flights)
    assert con.execute("SELECT COUNT(*) FROM raw_airlines").fetchone()[0] == len(pd.read_csv(raw_dir / "airlines.csv"))


def test_clean_run_has_no_failed_checks_and_known_warning(built):
    result = built[1]
    assert result["status"] == "ok" and result["checks_failed"] == 0
    warned = {r["check"] for r in result["results"] if r["status"] == "warn"}
    assert "flights_dest_known" in warned  # real data issue: destinations missing from airports table


def test_run_is_logged(con):
    assert con.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0] >= 1
    assert con.execute("SELECT COUNT(*) FROM dq_results").fetchone()[0] >= 10


def test_checks_catch_injected_corruption(raw_dir, tmp_path):
    """Corrupt a copy of the inputs; the checks must fail loudly (not silently pass)."""
    bad = tmp_path / "raw"
    shutil.copytree(raw_dir, bad)
    f = pd.read_csv(bad / "flights.csv")
    f.loc[0:4, "month"] = 13
    f.loc[5, "carrier"] = "ZZ"
    f.loc[6, "distance"] = -5
    f.to_csv(bad / "flights.csv", index=False)
    a = pd.read_csv(bad / "airlines.csv")
    pd.concat([a, a.iloc[[0]]]).to_csv(bad / "airlines.csv", index=False)
    out = pipeline.run(bad, tmp_path / "bad.duckdb")
    failed = {r["check"] for r in out["results"] if r["status"] == "fail"}
    assert out["status"] == "failed"
    assert {"flights_month_range", "flights_carrier_known", "flights_distance_positive",
            "airlines_carrier_unique"} <= failed
