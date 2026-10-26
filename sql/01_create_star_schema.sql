-- 01_create_star_schema.sql
-- Star schema for pilot-line fab reporting (Kimball style), PostgreSQL.
-- Dimensions describe things (date, product, tool, step, lot).
-- Facts record what happened (moves, lot results, tool hours, WIP).
--
-- Run:  psql -d fab_reporting -f sql/01_create_star_schema.sql
-- Then: psql -d fab_reporting -f sql/02_load_csv.sql

DROP SCHEMA IF EXISTS fab CASCADE;
CREATE SCHEMA fab;
SET search_path TO fab;

-- ---------- dimensions ----------
CREATE TABLE dim_date (
    date        DATE PRIMARY KEY,
    year        INT,
    month       TEXT,        -- '2026-07'
    iso_week    TEXT,        -- '2026-W28'
    weekday     TEXT
);

CREATE TABLE dim_product (
    product_id        TEXT PRIMARY KEY,
    product_name      TEXT,
    technology        TEXT,
    target_yield_pct  NUMERIC(5,1),
    target_ct_days    NUMERIC(5,2)   -- allowed cycle time for a normal lot
);

CREATE TABLE dim_tool (
    tool_id     TEXT PRIMARY KEY,    -- includes an 'UNKNOWN' member for bad source rows
    tool_group  TEXT,
    bay         TEXT
);

CREATE TABLE dim_step (
    step_key    TEXT PRIMARY KEY,    -- product + step number, e.g. 'P-LOGIC-07'
    product_id  TEXT REFERENCES dim_product,
    step_no     INT,
    step_name   TEXT,
    tool_group  TEXT
);

CREATE TABLE dim_lot (
    lot_id        TEXT PRIMARY KEY,
    product_id    TEXT REFERENCES dim_product,
    priority      TEXT,              -- 'NORMAL' or 'HOT'
    wafers_start  INT
);

-- ---------- facts ----------
-- grain: one lot at one process step
CREATE TABLE fact_lot_step (
    lot_id            TEXT REFERENCES dim_lot,
    step_key          TEXT REFERENCES dim_step,
    tool_id           TEXT REFERENCES dim_tool,
    date              DATE REFERENCES dim_date,   -- track-out date
    arrive_ts         TIMESTAMP,
    track_in_ts       TIMESTAMP,
    track_out_ts      TIMESTAMP,
    queue_hours       NUMERIC(8,2),
    hold_hours        NUMERIC(8,2),
    hold_reason       TEXT,
    process_hours     NUMERIC(8,2),               -- empty when timestamps are bad
    step_cycle_hours  NUMERIC(8,2),
    dq_flag           TEXT,
    PRIMARY KEY (lot_id, step_key)
);

-- grain: one finished lot
CREATE TABLE fact_lot (
    lot_id             TEXT PRIMARY KEY REFERENCES dim_lot,
    finish_date        DATE REFERENCES dim_date,
    cycle_time_days    NUMERIC(6,2),
    target_ct_days     NUMERIC(6,2),
    on_time            INT,          -- 1 = finished within target
    x_factor           NUMERIC(6,2), -- cycle time / pure process time
    raw_process_hours  NUMERIC(8,2),
    hold_hours         NUMERIC(8,2),
    wafers_start       INT,
    wafers_out         INT,
    die_yield_pct      NUMERIC(5,1)
);

-- grain: one tool on one day (hours add up to 24)
CREATE TABLE fact_tool_day (
    tool_id            TEXT REFERENCES dim_tool,
    date               DATE REFERENCES dim_date,
    pm_hours           NUMERIC(5,2),
    unscheduled_hours  NUMERIC(5,2),
    busy_hours         NUMERIC(5,2),
    up_hours           NUMERIC(5,2),
    idle_hours         NUMERIC(5,2),
    PRIMARY KEY (tool_id, date)
);

-- grain: one tool group at the end of one day (a snapshot)
CREATE TABLE fact_wip_day (
    date        DATE REFERENCES dim_date,
    tool_group  TEXT,
    wip_lots    INT,
    PRIMARY KEY (date, tool_group)
);
