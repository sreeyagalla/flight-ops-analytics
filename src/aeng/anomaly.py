"""Robust anomaly detection on a daily series: modified z-score against a trailing window.

score = 0.6745 * (x - median) / MAD, window = previous `window` days (current day excluded,
so a spike cannot mask itself). This is a simple statistical flag, not a causal explanation."""
import numpy as np
import pandas as pd


def detect(series: pd.Series, window: int = 28, threshold: float = 3.5, min_periods: int = 14) -> pd.DataFrame:
    s = series.astype(float)
    hist = s.shift(1)
    med = hist.rolling(window, min_periods=min_periods).median()
    mad = hist.rolling(window, min_periods=min_periods).apply(
        lambda w: np.nanmedian(np.abs(w - np.nanmedian(w))), raw=True)
    mad = mad.where(mad > 0)  # flat history -> undefined, never flagged
    score = 0.6745 * (s - med) / mad
    return pd.DataFrame({"value": s, "baseline": med, "score": score,
                         "is_anomaly": score.abs() >= threshold})


def daily_anomalies(con, metric: str = "avg_dep_delay", origin: str | None = None, **kw) -> pd.DataFrame:
    assert metric in ("avg_dep_delay", "cancel_rate")
    where, params = ("WHERE origin = ?", [origin]) if origin else ("", [])
    agg = {"avg_dep_delay": "SUM(avg_dep_delay * flights) / SUM(flights)",
           "cancel_rate": "SUM(cancel_rate * flights) / SUM(flights)"}[metric]
    df = con.execute(f"SELECT flight_date, {agg} AS v FROM mart_daily_origin {where} "
                     f"GROUP BY flight_date ORDER BY flight_date", params).df()
    res = detect(df.set_index("flight_date")["v"], **kw).reset_index()
    ctx = con.execute(f"SELECT flight_date, SUM(precip_in) AS precip_in, MAX(max_gust_mph) AS max_gust_mph "
                      f"FROM mart_daily_weather {where} GROUP BY flight_date", params).df()
    return res.merge(ctx, on="flight_date", how="left")
