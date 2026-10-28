import numpy as np
import pandas as pd

from aeng import docgen
from aeng.anomaly import daily_anomalies, detect
from aeng.metrics import METRICS


def test_injected_spike_is_flagged_and_quiet_series_is_not():
    rng = np.random.default_rng(0)
    base = pd.Series(10 + rng.normal(0, 1, 120))
    spiked = base.copy()
    spiked[80] += 15
    assert detect(spiked).is_anomaly[80]
    assert not detect(base).is_anomaly.any()


def test_flat_history_never_flagged():
    assert not detect(pd.Series([5.0] * 60 + [9.0])).is_anomaly.any()


def test_spike_does_not_contaminate_its_own_baseline():
    s = pd.Series([10.0, 11.0, 9.0, 10.5, 9.5] * 8 + [100.0])
    assert detect(s).is_anomaly.iloc[-1]


def test_real_data_flags_the_february_cancellation_storm(con):
    d = daily_anomalies(con, "cancel_rate").set_index("flight_date")
    assert d.loc[pd.Timestamp("2013-02-08"), "is_anomaly"] and d.loc[pd.Timestamp("2013-02-09"), "is_anomaly"]
    assert d.loc[pd.Timestamp("2013-02-09"), "value"] > 0.5


def test_data_dictionary_covers_every_metric(con):
    text = docgen.render(con)
    assert all(f"`{k}`" in text for k in METRICS)
    assert "fct_flights" in text
