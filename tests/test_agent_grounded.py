"""THE key test: every number in an agent answer must equal a number computed independently
(pandas straight from the raw CSV, no shared code with the DuckDB/semantic-layer path)."""
import json
import re

import pandas as pd
import pytest

from aeng.agent import ask

NUM = re.compile(r"\d[\d,]*\.?\d*")
HEADER_CONST = {"100"}  # the documented minimum-group-size footnote, not a data value


@pytest.fixture(scope="module")
def df(raw_dir):
    f = pd.read_csv(raw_dir / "flights.csv", na_values=["NA"])
    f = f.merge(pd.read_csv(raw_dir / "airlines.csv")[["carrier", "name"]], on="carrier", how="left")
    f["cancelled"] = f["dep_time"].isna()
    f["ontime"] = (f["arr_delay"] <= 15).where(f["arr_delay"].notna())
    return f


def numbers(text):
    return {n.rstrip(".").rstrip(",") for n in NUM.findall(text)} - HEADER_CONST


def pct(x): return f"{x * 100:.1f}"
def mins(x): return f"{x:.1f}"
def cnt(x): return f"{int(x):,}"


def grouped(df, by, fn, n_min=100):
    g = df.groupby(by)
    out = pd.DataFrame({"v": fn(g), "n": g.size()})
    return out[out.n >= n_min]


def test_overall_on_time(con, df):
    a = ask("What is the on-time arrival rate?", con)
    assert a.ok and numbers(a.text) == {pct(df.ontime.mean()), cnt(len(df))}


def test_filtered_count_united_july(con, df):
    a = ask("How many flights did United operate in July?", con)
    n = len(df[(df.carrier == "UA") & (df.month == 7)])
    assert a.ok and numbers(a.text) == {cnt(n)}


def test_filtered_rate_two_filters(con, df):
    a = ask("cancellation rate in February departing LGA", con)
    s = df[(df.month == 2) & (df.origin == "LGA")]
    assert numbers(a.text) == {pct(s.cancelled.mean()), cnt(len(s))}


def test_grouped_avg_dep_delay_by_origin(con, df):
    a = ask("What is the average departure delay by origin airport?", con)
    t = grouped(df, "origin", lambda g: g.dep_delay.mean())
    expected = {mins(v) for v in t.v} | {cnt(n) for n in t.n}
    assert numbers(a.text) == expected
    order = re.findall(r"- (\w+):", a.text)
    assert order == list(t.sort_values("v", ascending=False).index)


def test_worst_airline_on_time(con, df):
    a = ask("Which airline has the worst on-time rate?", con)
    t = grouped(df, "name", lambda g: g.ontime.mean()).sort_values("v").iloc[:1]
    assert numbers(a.text) == {pct(t.v.iloc[0]), cnt(t.n.iloc[0])}
    assert t.index[0] in a.text


def test_top3_destinations_arr_delay(con, df):
    a = ask("top 3 destinations by average arrival delay", con)
    t = grouped(df, "dest", lambda g: g.arr_delay.mean()).sort_values("v", ascending=False).iloc[:3]
    assert numbers(a.text) == {mins(v) for v in t.v} | {cnt(n) for n in t.n}
    assert re.findall(r"- (\w+):", a.text) == list(t.index)


def test_best_month_on_time(con, df):
    a = ask("Which month has the best on-time rate?", con)
    t = grouped(df, "month", lambda g: g.ontime.mean()).sort_values("v", ascending=False).iloc[:1]
    assert numbers(a.text) == {pct(t.v.iloc[0]), cnt(t.n.iloc[0])}


@pytest.mark.parametrize("q", [
    "Why was Delta late?",
    "How much revenue did JetBlue make?",
    "Predict next month cancellations",
    "How many passengers flew in March?",
    "What is the weather like?",
    "Tell me a joke",
])
def test_unsupported_questions_are_refused_without_numbers(con, q):
    a = ask(q, con)
    assert not a.ok
    assert "can't answer" in a.text
    assert not re.search(r"\d|%", a.text), "a refusal must not contain any data value"


def test_unknown_entity_is_never_invented(con):
    a = ask("on-time rate for flights to ZZZ", con)  # ZZZ is not an airport in the data
    assert "ZZZ" not in a.text


# ---- LLM translator path: the model may only pick a spec; numbers still come from SQL ----
class FakeClient:
    def __init__(self, payload):
        self.messages = self
        self.payload = payload

    def create(self, **kw):
        class R:
            content = [type("C", (), {"text": self.payload})()]
        return R()


def test_llm_spec_still_yields_sql_grounded_numbers(con, df):
    payload = json.dumps({"metric": "on_time_rate", "group_by": None, "filters": [["carrier", "DL"]],
                          "order": None, "limit": None, "answer": "It was 99.9%!"})  # extra text is ignored
    a = ask("how punctual is delta", con, llm_client=FakeClient(payload))
    s = df[df.carrier == "DL"]
    assert a.translator == "llm" and numbers(a.text) == {pct(s.ontime.mean()), cnt(len(s))}
    assert "99.9" not in a.text


@pytest.mark.parametrize("payload", [
    json.dumps({"metric": "revenue", "group_by": None, "filters": []}),
    json.dumps({"metric": "flights", "group_by": "pilot", "filters": []}),
    json.dumps({"metric": "flights", "filters": [["origin", "EWR'; DROP TABLE fct_flights;--"]]}),
    json.dumps({"metric": "flights", "filters": [["month", 99]]}),
    json.dumps({"unsupported": "asks about revenue"}),
])
def test_llm_hallucinated_or_hostile_specs_are_refused(con, payload):
    a = ask("some question", con, llm_client=FakeClient(payload))
    assert not a.ok
    assert con.execute("SELECT COUNT(*) FROM fct_flights").fetchone()[0] > 0


def test_llm_failure_falls_back_to_rules(con):
    a = ask("How many flights were there?", con, llm_client=FakeClient("not json"))
    assert a.ok and a.translator == "rules"
