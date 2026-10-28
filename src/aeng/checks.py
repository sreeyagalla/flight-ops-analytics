"""Declarative data-quality checks. Each check is a SQL query returning the number of
offending rows; status is derived from that count and the check's severity."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    name: str
    table: str
    description: str
    bad_rows_sql: str  # returns a single integer: count of violating rows
    severity: str = "error"  # "error" fails the pipeline; "warn" is reported only
    max_bad: int = 0  # tolerated violations before the check trips


CHECKS = [
    Check("flights_min_rows", "raw_flights", "Table is not unexpectedly small (>= 300,000 rows)",
          "SELECT CASE WHEN COUNT(*) >= 300000 THEN 0 ELSE 1 END FROM raw_flights"),
    Check("flights_key_not_null", "fct_flights", "flight_date, carrier, origin, dest are never null",
          "SELECT COUNT(*) FROM fct_flights WHERE flight_date IS NULL OR carrier IS NULL "
          "OR origin IS NULL OR dest IS NULL"),
    Check("airlines_carrier_unique", "raw_airlines", "carrier code is unique in dimension",
          "SELECT COUNT(*) - COUNT(DISTINCT carrier) FROM raw_airlines"),
    Check("flights_carrier_known", "fct_flights", "every flight's carrier exists in airlines",
          "SELECT COUNT(*) FROM raw_flights f ANTI JOIN raw_airlines a USING (carrier)"),
    Check("flights_origin_known", "fct_flights", "every origin airport exists in airports",
          "SELECT COUNT(*) FROM raw_flights f WHERE origin NOT IN (SELECT faa FROM raw_airports)"),
    Check("flights_dest_known", "fct_flights", "every destination airport exists in airports",
          "SELECT COUNT(*) FROM raw_flights f WHERE dest NOT IN (SELECT faa FROM raw_airports)",
          severity="warn"),
    Check("flights_month_range", "fct_flights", "month is between 1 and 12",
          "SELECT COUNT(*) FROM fct_flights WHERE month NOT BETWEEN 1 AND 12"),
    Check("flights_distance_positive", "fct_flights", "distance > 0",
          "SELECT COUNT(*) FROM fct_flights WHERE distance IS NULL OR distance <= 0"),
    Check("flights_dep_delay_plausible", "fct_flights", "departure delay within [-120, 1500] minutes",
          "SELECT COUNT(*) FROM fct_flights WHERE dep_delay NOT BETWEEN -120 AND 1500"),
    Check("flights_arr_missing_but_departed", "fct_flights",
          "departed flights with no arrival delay (diverted/incomplete); tolerated up to 1% of rows",
          "SELECT COUNT(*) FROM fct_flights WHERE NOT is_cancelled AND arr_delay IS NULL",
          severity="warn", max_bad=3367),
    Check("mart_reconciles_to_staging", "fct_flights", "fct_flights row count equals stg_flights",
          "SELECT ABS((SELECT COUNT(*) FROM fct_flights) - (SELECT COUNT(*) FROM stg_flights))"),
    Check("daily_mart_reconciles", "mart_daily_origin", "sum of daily flights equals fct_flights rows",
          "SELECT ABS((SELECT SUM(flights) FROM mart_daily_origin) - (SELECT COUNT(*) FROM fct_flights))"),
]


def run_checks(con, checks=CHECKS) -> list[dict]:
    out = []
    for c in checks:
        bad = int(con.execute(c.bad_rows_sql).fetchone()[0])
        status = "pass" if bad <= c.max_bad else ("fail" if c.severity == "error" else "warn")
        out.append({"check": c.name, "table_name": c.table, "description": c.description,
                    "severity": c.severity, "bad_rows": bad, "status": status})
    return out
