"""Build the static demo page (docs/index.html) from the REAL warehouse and the REAL agent.

Everything on the page is precomputed here by the same code the app uses; the page itself only renders it.
Run after the pipeline:  python scripts/build_site.py
"""
import json
from pathlib import Path

import duckdb

from aeng import config
from aeng.agent import QuerySpec, ask, build_sql
from aeng.anomaly import daily_anomalies
from aeng.metrics import DIMENSIONS, METRICS, MONTHS

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = [
    "Which airline has the worst on-time rate?",
    "Average departure delay by origin airport",
    "How many flights did United operate in July?",
    "Cancellation rate in February departing LGA",
    "Which month has the best on-time rate?",
    "Top 3 destinations by average arrival delay",
    "Why was Delta late?",
    "How much revenue did JetBlue make?",
]


def explore(con):
    out = {}
    for mk in METRICS:
        out[mk] = {}
        for dk in DIMENSIONS:
            spec = QuerySpec(mk, dk, (), "desc", 15 if dk == "dest" else None)
            sql, params = build_sql(spec)
            rows = con.execute(sql, params).fetchall()
            out[mk][dk] = [{"label": MONTHS[int(g) - 1][:3] if dk == "month" else str(g), "value": v, "n": n}
                           for g, v, n in rows]
    return out


def anomalies(con):
    out = {}
    for key in ("cancel_rate", "avg_dep_delay"):
        d = daily_anomalies(con, key)
        out[key] = [{"d": str(r.flight_date)[:10], "v": round(r.value, 4),
                     "b": None if r.baseline != r.baseline else round(r.baseline, 4),
                     "flag": bool(r.is_anomaly)} for r in d.itertuples()]
    return out


def main():
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    qa = []
    for q in QUESTIONS:
        a = ask(q, con)
        qa.append({"q": q, "ok": a.ok, "text": a.text, "sql": a.sql,
                   "spec": None if not a.spec else {"metric": a.spec.metric, "group_by": a.spec.group_by,
                                                    "filters": [list(f) for f in a.spec.filters],
                                                    "order": a.spec.order, "limit": a.spec.limit}})
    n, d0, d1, ncar, ndest = con.execute(
        "SELECT COUNT(*), MIN(flight_date), MAX(flight_date), COUNT(DISTINCT carrier), COUNT(DISTINCT dest) "
        "FROM fct_flights").fetchone()
    dq = con.execute('SELECT status, "check", description, bad_rows FROM dq_results '
                     "ORDER BY CASE status WHEN 'fail' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END, \"check\"").fetchall()
    anom = anomalies(con)
    data = {
        "summary": {"flights": n, "from": str(d0), "to": str(d1), "airlines": ncar, "dests": ndest,
                    "checks": len(dq), "warned": sum(r[0] == "warn" for r in dq),
                    "flagged_cancel": sum(p["flag"] for p in anom["cancel_rate"])},
        "metrics": {k: {"label": m.label, "unit": m.unit, "definition": m.definition} for k, m in METRICS.items()},
        "dims": {k: v[2].split(" (")[0] for k, v in DIMENSIONS.items()},
        "explore": explore(con), "anomalies": anom, "qa": qa,
        "dq": [{"status": s, "check": c, "description": ds, "bad": b} for s, c, ds, b in dq],
    }
    tpl = (ROOT / "scripts" / "site_template.html").read_text(encoding="utf-8")
    out = ROOT / "docs" / "index.html"
    out.write_text(tpl.replace("__DATA__", json.dumps(data, separators=(",", ":"))), encoding="utf-8")
    print("wrote", out, f"({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
