-- Mart: one row per flight, with dimensions attached. is_cancelled follows the
-- dataset convention: no actual departure time recorded.
CREATE OR REPLACE TABLE fct_flights AS
SELECT
    f.flight_date, f.month, f.carrier,
    COALESCE(a.name, f.carrier) AS carrier_name,
    f.origin, f.dest, f.dep_delay, f.arr_delay, f.distance,
    (f.dep_time IS NULL) AS is_cancelled
FROM stg_flights f
LEFT JOIN raw_airlines a USING (carrier);

-- Daily departure performance by origin: input to anomaly detection.
CREATE OR REPLACE TABLE mart_daily_origin AS
SELECT flight_date, origin,
       COUNT(*) AS flights,
       AVG(dep_delay) AS avg_dep_delay,
       AVG(CASE WHEN is_cancelled THEN 1.0 ELSE 0.0 END) AS cancel_rate
FROM fct_flights
GROUP BY ALL;

CREATE OR REPLACE TABLE mart_daily_weather AS
SELECT origin, obs_date AS flight_date,
       SUM(precip) AS precip_in, MAX(wind_gust) AS max_gust_mph, MIN(visib) AS min_visib_mi
FROM stg_weather
GROUP BY ALL;
