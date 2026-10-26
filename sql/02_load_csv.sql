-- 02_load_csv.sql
-- Loads the CSV files from data/clean/ into the fab schema.
-- Run from the project folder (so the relative paths work):
--   psql -d fab_reporting -f sql/02_load_csv.sql
-- Order matters: dimensions first, then facts (because of the foreign keys).

SET search_path TO fab;

\copy dim_date      FROM 'data/clean/dim_date.csv'      CSV HEADER
\copy dim_product   FROM 'data/clean/dim_product.csv'   CSV HEADER
\copy dim_tool      FROM 'data/clean/dim_tool.csv'      CSV HEADER
\copy dim_step      FROM 'data/clean/dim_step.csv'      CSV HEADER
\copy dim_lot       FROM 'data/clean/dim_lot.csv'       CSV HEADER
\copy fact_lot_step FROM 'data/clean/fact_lot_step.csv' CSV HEADER
\copy fact_lot      FROM 'data/clean/fact_lot.csv'      CSV HEADER
\copy fact_tool_day (tool_id, date, pm_hours, unscheduled_hours, busy_hours, up_hours, idle_hours) FROM 'data/clean/fact_tool_day.csv' CSV HEADER
\copy fact_wip_day  FROM 'data/clean/fact_wip_day.csv'  CSV HEADER
