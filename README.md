# Flight Ops Analytics: a self-serve analytics engineering starter

A small, runnable analytics platform on **real public flight data**. It has a reproducible pipeline with automated data-quality checks, a governed metric layer, anomaly detection, a Streamlit self-service app, and a natural-language Q&A agent that is **structurally prevented from inventing numbers**. It runs entirely locally with **no API keys and nothing paid**.

**Live demo (static, precomputed from the real pipeline and agent): https://sreeyagalla.github.io/flight-ops-analytics/**

## What it demonstrates

| Capability | Where |
|---|---|
| Reproducible pipeline (raw CSV, then staging, then marts) with pinned input checksums | `scripts/fetch_data.py`, `src/aeng/pipeline.py`, `src/aeng/sql/` |
| Declarative data-quality validation, with severities and a persisted run log | `src/aeng/checks.py`, tables `dq_results`, `pipeline_runs` |
| Governed metric definitions (one source of truth for app, agent and docs) | `src/aeng/metrics.py` |
| Self-service exploration for non-technical users | `app/streamlit_app.py` |
| Trend/anomaly detection with visual storytelling | `src/aeng/anomaly.py`, "Anomalies" tab |
| Grounded NL Q&A with refusal of unsupported questions | `src/aeng/agent.py`, `tests/test_agent_grounded.py` |
| Documentation generated from code | `src/aeng/docgen.py` → `docs/DATA_DICTIONARY.md` |

## Quick start (Python 3.10+)

```bash
pip install -e ".[dev]"
python scripts/fetch_data.py        # downloads public CSVs, verifies SHA-256 checksums
python -m aeng.pipeline             # builds data/warehouse.duckdb and runs the quality checks
python -m pytest                    # 30 tests
streamlit run app/streamlit_app.py  # the UI
python -m aeng.agent "Which airline has the worst on-time rate?"   # CLI
python scripts/build_site.py        # regenerates the static demo page docs/index.html
```

## Architecture

```
 public CSVs (nycflights13)
        │  fetch_data.py (checksum-pinned)
        ▼
  raw_* tables ──► stg_* (typing) ──► fct_flights, mart_daily_* ──► data-quality checks
   (DuckDB)                                  │                         │
                                             │                         └─► dq_results, pipeline_runs
                         ┌───────────────────┼────────────────────┐
                         ▼                   ▼                    ▼
                  metrics.py (semantic layer: the only queryable metrics/dimensions)
                         │                   │                    │
                    Streamlit app        anomaly.py            agent.py
                    (Explore/Health)    (robust z-score)   question → QuerySpec → validated SQL
                                                            → template renders numbers from rows
```

## Key design decisions

- **The LLM never writes numbers.** The agent turns a question into a `QuerySpec` (metric, dimension, filters, order, limit) drawn from a whitelist. It validates the spec, builds SQL with bound parameters, runs it, and renders the answer from a template over the result rows. Unknown metrics, dimensions or entities, and causal or predictive questions ("why…", "forecast…", "revenue…"), get an explicit refusal listing what is supported.
- **Rules by default, LLM optional.** The default translator is deterministic regex/rules. If `ANTHROPIC_API_KEY` is set (and `pip install -e ".[llm]"`), an LLM translates the question to the *same* spec, which goes through the *same* validation. If the LLM call fails, the agent falls back to the rules.
- **One metric layer.** The dashboard, agent and data dictionary all read `metrics.py`, so definitions can't drift apart. On-time means an arrival of 15 minutes late or less. Cancelled means no actual departure time recorded.
- **Small groups are hidden.** Grouped answers exclude groups under 100 flights so rankings aren't dominated by noise. The footnote is part of every grouped answer.
- **Checks fail loudly.** Error-severity checks make the pipeline exit non-zero. Warnings are reported but tolerated. Staging uses `TRY(make_date(...))` so a corrupt date reaches the checks and is reported instead of crashing the transform. A test found that bug.
- **Anomaly detection is deliberately simple and causally modest.** It uses a modified z-score (median/MAD) against the *previous* 28 days, with the current day excluded so a spike can't mask itself. Weather columns are shown as context only.

## Tests and what they prove

`python -m pytest` → **30 passed**.

- **Grounding test (`tests/test_agent_grounded.py`).** For 7 representative questions (overall, filtered, multi-filter, grouped, ranked, top-N), the set of numbers in the agent's answer must equal the set computed *independently* with pandas straight from the raw CSV. That path shares no code with DuckDB or the semantic layer. Ranking order is checked too.
- **Refusal tests.** Six unsupported questions are refused, and the refusal text must contain no digits or percent signs. Hostile or hallucinated LLM specs (unknown metric, unknown dimension, SQL-injection-style filter value, month 99, "unsupported") are refused. Extra "answer" text smuggled into an LLM response is ignored.
- **Pipeline tests.** Row counts reconcile to the source CSVs. Corrupted copies of the inputs (bad month, orphan carrier, negative distance, duplicate key) must trip the matching checks.
- **Anomaly tests.** An injected spike is flagged, a quiet series isn't, and flat history never flags. On the real data, 2013-02-08 and 2013-02-09 are flagged as cancellation-rate anomalies (rate above 50% on 02-09).

## Honest scope

**Real**
- All data is real and public: the nycflights13 dataset (US DOT/BTS flight records plus NOAA weather), mirrored via Rdatasets. It holds 336,776 flights from 2013-01-01 to 2013-12-31, from 3 origin airports, across 16 airlines and 105 destinations. **Nothing is synthetic or simulated.**
- Pipeline outputs, check results and every figure the app shows are computed from that data.

**Real findings from running it** (these are properties of the dataset, not product claims)
- 1 warning on the clean data: 7,602 flights (4 destination codes) have destinations missing from the airports table.
- 1,175 departed flights have no arrival record. This is within the tolerance set for that check, and those flights are excluded from arrival-based metrics.
- Anomaly counts at the default threshold (all origins): 32 days flagged on departure delay and 68 on cancellation rate. These are counts of flagged days, not measures of detector accuracy, and I did not evaluate against labelled ground truth.

**Not built / limitations**
- There is no user/access management, lifecycle management or cloud deployment. Storage is a local DuckDB file, not a cloud platform.
- There is no ML model, so no model fairness or interpretability analysis. The anomaly detector is a statistical rule.
- The rule-based question parser is regex-based and brittle on phrasing it hasn't seen. It refuses when unsure, but it can also misread an unusual question. Check the "How this was computed" panel.
- **The optional LLM path has been tested only against a fake client**, covering the spec parsing, validation and fallback. It has not been run against a live API. The default is the rule-based translator.
- There are no real users or stakeholders, so there are no usage or adoption results. The data covers a single year and three airports, so findings say nothing about other periods.
- The dashboard was verified headlessly with Streamlit's `AppTest` (all four tabs render and the Q&A flow works) and by confirming the server responds. It was not visually reviewed in a browser.

## Data

`data/raw/*.csv` is not committed. `scripts/fetch_data.py` downloads it from the public Rdatasets mirror and verifies SHA-256 checksums pinned in `data/checksums.txt`. The upstream package is documented at https://github.com/hadley/nycflights13.
