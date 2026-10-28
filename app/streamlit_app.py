"""Self-serve front end. Run: streamlit run app/streamlit_app.py"""
import duckdb
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from aeng import config
from aeng.agent import QuerySpec, ask, build_sql
from aeng.anomaly import daily_anomalies
from aeng.metrics import DIMENSIONS, METRICS, MIN_GROUP_FLIGHTS, MONTHS, fmt

BAR, FLAG, MUTED = "#2a6fdb", "#d1495b", "#8a8f98"

st.set_page_config(page_title="Flight Ops Analytics", layout="wide")


@st.cache_resource
def get_con():
    return duckdb.connect(str(config.DB_PATH), read_only=True)


def style(fig, height=380):
    fig.update_layout(height=height, margin=dict(l=8, r=8, t=30, b=8), template=None,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      legend=dict(orientation="h", y=1.1))
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.2)")
    return fig


if not config.DB_PATH.exists():
    st.error("Warehouse not built. Run `python scripts/fetch_data.py` then `python -m aeng.pipeline`.")
    st.stop()
con = get_con()

st.title("Flight operations analytics")
st.caption("Real public data: all 336,776 flights departing NYC-area airports in 2013 (nycflights13). "
           "Every number below is computed by SQL over the governed metric definitions.")
tab_ask, tab_explore, tab_anom, tab_health = st.tabs(["Ask a question", "Explore", "Anomalies", "Pipeline health"])

with tab_ask:
    st.write("Ask in plain English. Answers come only from computed data; unsupported questions are declined.")
    examples = ["Which airline has the worst on-time rate?", "Average departure delay by origin airport",
                "Cancellation rate in February departing LGA", "Top 3 destinations by average arrival delay",
                "Why was Delta late?"]
    q = st.selectbox("Examples", [""] + examples)
    q = st.text_input("Your question", value=q)
    if q:
        a = ask(q, con)
        (st.success if a.ok else st.warning)(a.text)
        if a.ok:
            with st.expander("How this was computed (SQL + query spec)"):
                st.code(a.sql, language="sql")
                st.json({"translator": a.translator, "spec": a.spec.__dict__ | {"filters": list(a.spec.filters)}})

with tab_explore:
    c1, c2, c3 = st.columns(3)
    mkey = c1.selectbox("Metric", list(METRICS), format_func=lambda k: METRICS[k].label)
    dkey = c2.selectbox("Break down by", list(DIMENSIONS), format_func=lambda k: DIMENSIONS[k][2].split(" (")[0])
    month = c3.selectbox("Month", [0] + list(range(1, 13)), format_func=lambda i: "All year" if i == 0 else MONTHS[i - 1])
    m = METRICS[mkey]
    spec = QuerySpec(mkey, dkey, (("month", month),) if month else (), "desc", 25 if dkey in ("dest",) else None)
    sql, params = build_sql(spec)
    df = con.execute(sql, params).df()
    if df.empty:
        st.info("No groups with enough flights.")
    else:
        if dkey == "month":
            df["grp"] = df["grp"].map(lambda i: MONTHS[int(i) - 1][:3])
        fig = go.Figure(go.Bar(x=df["grp"], y=df["value"], marker_color=BAR, customdata=df["n"],
                               hovertemplate="%{x}<br>" + m.label + ": %{y:.3f}<br>n = %{customdata:,} flights<extra></extra>"))
        fig.update_layout(title=f"{m.label} by {DIMENSIONS[dkey][2].split(' (')[0].lower()}"
                                + (f", {MONTHS[month - 1]}" if month else ""))
        if m.unit == "pct":
            fig.update_yaxes(tickformat=".0%")
        st.plotly_chart(style(fig), width="stretch")
        st.caption(f"{m.definition} Groups under {MIN_GROUP_FLIGHTS} flights are hidden. Dest view shows top 25.")
        with st.expander("Table view"):
            show = df.assign(value=[fmt(m, v) for v in df["value"]]).rename(columns={"grp": DIMENSIONS[dkey][2], "n": "flights"})
            st.dataframe(show, hide_index=True)

with tab_anom:
    c1, c2 = st.columns(2)
    am = c1.selectbox("Series", ["cancel_rate", "avg_dep_delay"],
                      format_func={"cancel_rate": "Daily cancellation rate", "avg_dep_delay": "Daily average departure delay (min)"}.get)
    ao = c2.selectbox("Origin", ["All", "EWR", "JFK", "LGA"])
    d = daily_anomalies(con, am, None if ao == "All" else ao)
    flagged = d[d.is_anomaly]
    fig = go.Figure()
    fig.add_scatter(x=d.flight_date, y=d.value, mode="lines", name="Daily value", line=dict(color=BAR, width=2))
    fig.add_scatter(x=d.flight_date, y=d.baseline, mode="lines", name="28-day trailing median",
                    line=dict(color=MUTED, width=1.5, dash="dot"))
    fig.add_scatter(x=flagged.flight_date, y=flagged.value, mode="markers", name="Flagged (|score| >= 3.5)",
                    marker=dict(color=FLAG, size=9, line=dict(color="white", width=2)))
    if am == "cancel_rate":
        fig.update_yaxes(tickformat=".0%")
    st.plotly_chart(style(fig, 420), width="stretch")
    st.caption("Modified z-score vs the previous 28 days. A statistical flag, not a diagnosis: the weather columns "
               "are context only and no causal claim is made.")
    st.dataframe(flagged[["flight_date", "value", "baseline", "score", "precip_in", "max_gust_mph"]]
                 .rename(columns={"precip_in": "precip (in)", "max_gust_mph": "max gust (mph)"}).round(3),
                 hide_index=True)

with tab_health:
    runs = con.execute("SELECT * FROM pipeline_runs ORDER BY run_at DESC").df()
    last = runs.iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Last run", last.status.upper())
    c2.metric("Rows processed", f"{int(last.flights_rows):,}")
    c3.metric("Checks failed", int(last.checks_failed))
    c4.metric("Checks warned", int(last.checks_warned))
    dq = con.execute("SELECT status, \"check\", table_name, bad_rows, description FROM dq_results "
                     "ORDER BY CASE status WHEN 'fail' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END, \"check\"").df()
    dq["status"] = dq["status"].map({"pass": "PASS", "warn": "WARN", "fail": "FAIL"})
    st.dataframe(dq, hide_index=True, width="stretch")
    st.caption("Checks are declarative SQL in src/aeng/checks.py. Errors fail the pipeline; warnings are reported.")
    st.subheader("Run history")
    st.dataframe(runs, hide_index=True, width="stretch")
