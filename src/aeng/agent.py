"""Grounded natural-language analytics agent.

Guardrail design:
  * A question is translated into a QuerySpec (metric/dimension/filters/order/limit) drawn ONLY from the
    semantic layer whitelist (metrics.py). Default translator = deterministic rules (no API key needed).
    Optional translator = an LLM that outputs the same JSON spec; its output goes through the SAME validation.
  * SQL is built from the validated spec; filter values are bound parameters.
  * The answer text is rendered from the SQL result rows by a template. No LLM ever writes a number.
  * Anything outside the whitelist (unknown metric, forecasts, causes, unsupported filters) is refused.
"""
import json
import os
import re
from dataclasses import dataclass, field

import duckdb

from . import config
from .metrics import DIMENSIONS, METRICS, MIN_GROUP_FLIGHTS, MONTHS, fmt

UNSUPPORTED = re.compile(
    r"\b(why|cause[sd]?|because|predict\w*|forecast\w*|will|next (year|month|week)|revenue|price|fare|cost|"
    r"profit|passenger\w*|fuel|safety|crash\w*|salary|customer\w*)\b", re.I)

ALIASES = {"newark": "EWR", "laguardia": "LGA", "kennedy": "JFK"}
DIM_WORDS = {"airline": "carrier", "carrier": "carrier", "origin": "origin", "departure airport": "origin",
             "destination": "dest", "month": "month", "airport": "origin"}


@dataclass(frozen=True)
class QuerySpec:
    metric: str
    group_by: str | None = None
    filters: tuple = ()  # tuple of (dimension, value) pairs
    order: str | None = None  # "desc" | "asc"
    limit: int | None = None


@dataclass
class Answer:
    ok: bool
    text: str
    spec: QuerySpec | None = None
    sql: str | None = None
    rows: list = field(default_factory=list)
    translator: str = "rules"


def supported_help() -> str:
    return ("I can answer questions about: " + ", ".join(m.label.lower() for m in METRICS.values()) +
            "; optionally broken down by " + ", ".join(d[2].split(" (")[0].lower() for d in DIMENSIONS.values()) +
            ", and filtered by airline, airport or month. Example: 'Which airline has the worst on-time rate?'")


def refuse(reason: str) -> Answer:
    return Answer(False, f"I can't answer that from the data this system supports ({reason}). {supported_help()}")


# ---------- validation + SQL ----------
def validate(spec: QuerySpec, con) -> None:
    if spec.metric not in METRICS:
        raise ValueError(f"unknown metric {spec.metric!r}")
    if spec.group_by is not None and spec.group_by not in DIMENSIONS:
        raise ValueError(f"unknown dimension {spec.group_by!r}")
    if spec.order not in (None, "asc", "desc"):
        raise ValueError("bad order")
    if spec.limit is not None and not (isinstance(spec.limit, int) and 1 <= spec.limit <= 50):
        raise ValueError("bad limit")
    for dim, val in spec.filters:
        if dim not in DIMENSIONS:
            raise ValueError(f"unknown filter dimension {dim!r}")
        col = DIMENSIONS[dim][1]
        if dim == "month":
            ok = isinstance(val, int) and 1 <= val <= 12
        else:
            ok = con.execute(f"SELECT COUNT(*) FROM fct_flights WHERE {col} = ?", [val]).fetchone()[0] > 0
        if not ok:
            raise ValueError(f"filter value {val!r} not found for {dim}")


def build_sql(spec: QuerySpec) -> tuple[str, list]:
    m = METRICS[spec.metric]
    where, params = [], []
    for dim, val in spec.filters:
        where.append(f"{DIMENSIONS[dim][1]} = ?")
        params.append(val)
    w = f"WHERE {' AND '.join(where)}" if where else ""
    if spec.group_by is None:
        return f"SELECT {m.sql} AS value, COUNT(*) AS n FROM fct_flights {w}", params
    disp = DIMENSIONS[spec.group_by][0]
    direction = (spec.order or "desc").upper()
    lim = f"LIMIT {int(spec.limit)}" if spec.limit else ""
    return (f"SELECT {disp} AS grp, {m.sql} AS value, COUNT(*) AS n FROM fct_flights {w} "
            f"GROUP BY {disp} HAVING COUNT(*) >= {MIN_GROUP_FLIGHTS} "
            f"ORDER BY value {direction} NULLS LAST, grp {lim}"), params


# ---------- rendering (the only place numbers become text) ----------
def _grp_label(dim: str, g) -> str:
    return MONTHS[int(g) - 1] if dim == "month" else str(g)


def _scope(spec: QuerySpec, con) -> str:
    parts = []
    for dim, val in spec.filters:
        if dim == "month":
            parts.append(f"in {MONTHS[val - 1]}")
        elif dim == "carrier":
            name = con.execute("SELECT MAX(carrier_name) FROM fct_flights WHERE carrier=?", [val]).fetchone()[0]
            parts.append(f"for {name}")
        elif dim == "origin":
            parts.append(f"departing {val}")
        else:
            parts.append(f"arriving at {val}")
    return " ".join(parts)


def render(spec: QuerySpec, rows: list, con) -> str:
    m = METRICS[spec.metric]
    scope = _scope(spec, con)
    if spec.group_by is None:
        value, n = rows[0]
        if not n:
            return "No flights match that filter."
        return f"{m.label} {scope}: {fmt(m, value)} (n = {n:,} flights)".replace(" :", ":").replace("  ", " ")
    if not rows:
        return "No groups with enough flights match that filter."
    head = f"{m.label} by {DIMENSIONS[spec.group_by][2].split(' (')[0].lower()} {scope}".replace("  ", " ").strip()
    lines = [f"- {_grp_label(spec.group_by, g)}: {fmt(m, v)} (n = {n:,} flights)" for g, v, n in rows]
    return head + f" (groups with fewer than {MIN_GROUP_FLIGHTS} flights excluded):\n" + "\n".join(lines)


# ---------- rule-based translator ----------
def _entities(con):
    carriers = dict(con.execute("SELECT DISTINCT carrier, carrier_name FROM fct_flights").fetchall())
    first_words = {}
    for code, name in carriers.items():
        first_words.setdefault(name.split()[0].lower(), set()).add(code)
    name_words = {w: next(iter(c)) for w, c in first_words.items() if len(c) == 1}
    airports = {r[0] for r in con.execute(
        "SELECT origin FROM fct_flights UNION SELECT dest FROM fct_flights").fetchall()}
    origins = {r[0] for r in con.execute("SELECT DISTINCT origin FROM fct_flights").fetchall()}
    return carriers, name_words, airports, origins


def _order(ql: str, higher_is_worse) -> str | None:
    if re.search(r"\bworst\b", ql):
        return "asc" if higher_is_worse is False else "desc"
    if re.search(r"\bbest\b", ql):
        return "asc" if higher_is_worse is True else "desc"
    if re.search(r"\b(lowest|fewest|least|shortest|smallest)\b", ql):
        return "asc"
    if re.search(r"\b(highest|most|longest|top|biggest|largest)\b", ql):
        return "desc"
    return None


def parse_rules(q: str, con) -> QuerySpec | None:
    ql = q.lower()
    if "cancel" in ql:
        metric = "cancellation_rate"
    elif re.search(r"on[- ]?time|punctual", ql):
        metric = "on_time_rate"
    elif re.search(r"arriv\w* delay|delay\w* (?:on )?arriv|arrive late|late arriv", ql):
        metric = "avg_arr_delay"
    elif re.search(r"delay|\blate\b", ql):
        metric = "avg_dep_delay"
    elif re.search(r"how many|number of|count|total", ql) and "flight" in ql:
        metric = "flights"
    else:
        return None
    dim_re = r"(airline|carrier|origin|departure airport|destination|month|airport)s?"
    m = (re.search(rf"\b(?:by|per|each|which|every)\s+{dim_re}\b", ql)
         or re.search(rf"\b(?:top|worst|best)\s+(?:\d+\s+)?{dim_re}\b", ql))
    group_by = DIM_WORDS[m.group(1)] if m else None
    carriers, name_words, airports, origins = _entities(con)
    filters = []
    for i, mn in enumerate(MONTHS, 1):
        if re.search(rf"\b{mn.lower()}\b", ql):
            filters.append(("month", i))
    for w, code in name_words.items():
        if re.search(rf"\b{re.escape(w)}\b", ql):
            filters.append(("carrier", code))
    for tok in re.findall(r"\b[A-Z0-9]{2}\b", q):
        if tok in carriers and ("carrier", tok) not in filters:
            filters.append(("carrier", tok))
    for tok in re.findall(r"\b[A-Z]{3}\b", q) + [ALIASES[w] for w in ALIASES if w in ql]:
        if tok not in airports:
            continue
        to_pat = re.search(rf"\b(?:to|into|arriving (?:at|in))\s+{tok}\b", q)
        filters.append(("dest" if to_pat or tok not in origins else "origin", tok))
    order = _order(ql, METRICS[metric].higher_is_worse)
    limit = None
    tn = re.search(r"\b(?:top|worst|best) (\d+)\b|\b(\d+) (?:worst|best)\b", ql)
    if tn:
        limit = int(next(g for g in tn.groups() if g))
    elif order and group_by:
        limit = 1
    if group_by and order is None:
        order = "desc"
    return QuerySpec(metric, group_by, tuple(filters), order, limit)


# ---------- optional LLM translator (spec only; never produces numbers) ----------
LLM_SYSTEM = (
    "Translate the user's question into a JSON query spec. Output ONLY JSON: "
    '{"metric": one of %s, "group_by": one of %s or null, "filters": [[dimension, value]], '
    '"order": "asc"|"desc"|null, "limit": int|null}. month filter values are integers 1-12; carrier is a '
    "two-letter code; origin/dest are 3-letter airport codes. If the question cannot be expressed with "
    'these, output {"unsupported": "<reason>"}. Never include numbers from your own knowledge.'
    % (list(METRICS), list(DIMENSIONS)))


def parse_llm(q: str, client=None, model: str | None = None):
    """Returns a QuerySpec, or a str reason if unsupported. `client` is anthropic.Anthropic-like."""
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    resp = client.messages.create(model=model or os.environ.get("AENG_LLM_MODEL", "claude-haiku-5-5"),
                                  max_tokens=300, system=LLM_SYSTEM,
                                  messages=[{"role": "user", "content": q}])
    data = json.loads(resp.content[0].text)
    if "unsupported" in data:
        return str(data["unsupported"])
    return QuerySpec(data["metric"], data.get("group_by"),
                     tuple((d, v) for d, v in data.get("filters", [])),
                     data.get("order"), data.get("limit"))


# ---------- entry point ----------
def ask(question: str, con=None, llm_client=None) -> Answer:
    own = con is None
    con = con or duckdb.connect(str(config.DB_PATH), read_only=True)
    try:
        if UNSUPPORTED.search(question):
            return refuse("it asks for causes, predictions or data outside the flight-operations metrics")
        translator, spec = "rules", None
        if llm_client is not None or os.environ.get("ANTHROPIC_API_KEY"):
            try:
                out = parse_llm(question, llm_client)
                if isinstance(out, str):
                    return refuse(out)
                spec, translator = out, "llm"
            except Exception:
                spec = None  # any LLM failure falls back to the deterministic rules
        if spec is None:
            spec = parse_rules(question, con)
        if spec is None:
            return refuse("I couldn't map it to a known metric")
        try:
            validate(spec, con)
        except (ValueError, TypeError) as e:
            return refuse(str(e))
        sql, params = build_sql(spec)
        rows = con.execute(sql, params).fetchall()
        return Answer(True, render(spec, rows, con), spec, sql, rows, translator)
    finally:
        if own:
            con.close()


if __name__ == "__main__":
    import sys
    print(ask(" ".join(sys.argv[1:])).text)
