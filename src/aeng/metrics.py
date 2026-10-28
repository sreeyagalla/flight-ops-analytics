"""Semantic layer: the ONLY metrics and dimensions the app and agent can query.
Definitions live in one place so dashboards, the agent and the docs cannot drift apart."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    sql: str  # aggregate expression over fct_flights
    unit: str  # "count" | "pct" | "min"
    higher_is_worse: bool | None
    definition: str


METRICS = {m.key: m for m in [
    Metric("flights", "Number of flights", "COUNT(*)", "count", None,
           "Count of scheduled flights, including cancelled."),
    Metric("avg_dep_delay", "Average departure delay", "AVG(dep_delay)", "min", True,
           "Mean of departure delay in minutes (early = negative). Cancelled flights have no delay and are excluded."),
    Metric("avg_arr_delay", "Average arrival delay", "AVG(arr_delay)", "min", True,
           "Mean arrival delay in minutes. Flights with no arrival record are excluded."),
    Metric("on_time_rate", "On-time arrival rate",
           "AVG(CASE WHEN arr_delay IS NULL THEN NULL WHEN arr_delay <= 15 THEN 1.0 ELSE 0.0 END)",
           "pct", False,
           "Share of flights with a recorded arrival that arrived <= 15 minutes after schedule."),
    Metric("cancellation_rate", "Cancellation rate",
           "AVG(CASE WHEN is_cancelled THEN 1.0 ELSE 0.0 END)", "pct", True,
           "Share of flights with no actual departure recorded."),
]}

# dimension key -> (display column, filter column, description)
DIMENSIONS = {
    "carrier": ("carrier_name", "carrier", "Airline"),
    "origin": ("origin", "origin", "Origin airport (departures from the three NYC-area airports)"),
    "dest": ("dest", "dest", "Destination airport"),
    "month": ("month", "month", "Calendar month"),
}

MIN_GROUP_FLIGHTS = 100  # grouped answers exclude tiny groups so rates aren't dominated by noise
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]


def fmt(metric: Metric, v) -> str:
    if v is None:
        return "n/a"
    if metric.unit == "pct":
        return f"{v * 100:.1f}%"
    if metric.unit == "min":
        return f"{v:.1f} min"
    return f"{int(v):,}"
