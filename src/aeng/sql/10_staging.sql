-- Staging: light typing/renaming only. No business logic.
CREATE OR REPLACE TABLE stg_flights AS
SELECT
    TRY(make_date(year, month, day)) AS flight_date,
    year, month, day,
    carrier, flight, tailnum, origin, dest,
    dep_time, dep_delay, arr_delay, air_time, distance,
    hour AS sched_hour
FROM raw_flights;

CREATE OR REPLACE TABLE stg_weather AS
SELECT origin, TRY(make_date(year, month, day)) AS obs_date, hour,
       temp, wind_speed, wind_gust, precip, visib
FROM raw_weather;
