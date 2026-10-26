-- 03_kpi_queries.sql
-- The questions Fab stakeholders asked (see docs/01_business_brief.md),
-- answered in SQL. The same numbers must appear in Power BI: that is how
-- the dashboard is tested (see docs/04_test_plan.md).

SET search_path TO fab;

-- Q1. Weekly output, cycle time and on-time delivery (Operations manager)
SELECT d.iso_week,
       COUNT(*)                              AS lots_out,
       ROUND(AVG(l.cycle_time_days), 2)      AS avg_cycle_time_days,
       ROUND(100.0 * AVG(l.on_time), 1)      AS on_time_pct
FROM fact_lot l
JOIN dim_date d ON d.date = l.finish_date
GROUP BY d.iso_week
ORDER BY d.iso_week;

-- Q2. Where do lots wait? Queue time per tool group (Line manager)
-- The group with the most total queue hours is the bottleneck.
SELECT s.tool_group,
       COUNT(*)                                    AS visits,
       ROUND(AVG(f.queue_hours), 1)                AS avg_queue_h,
       ROUND(SUM(f.queue_hours))                   AS total_queue_h,
       ROUND(100.0 * SUM(f.queue_hours) / SUM(SUM(f.queue_hours)) OVER (), 1) AS share_of_all_waiting_pct
FROM fact_lot_step f
JOIN dim_step s ON s.step_key = f.step_key
GROUP BY s.tool_group
ORDER BY total_queue_h DESC;

-- Q3. Tool availability and utilization per tool (Equipment engineer)
--   availability = up hours / all hours
--   utilization  = busy hours / up hours
SELECT t.tool_group,
       t.tool_id,
       ROUND(100.0 * SUM(f.up_hours) / SUM(f.up_hours + f.pm_hours + f.unscheduled_hours), 1) AS availability_pct,
       ROUND(100.0 * SUM(f.busy_hours) / NULLIF(SUM(f.up_hours), 0), 1)                         AS utilization_pct,
       ROUND(SUM(f.unscheduled_hours), 1)                                                       AS unscheduled_down_h
FROM fact_tool_day f
JOIN dim_tool t ON t.tool_id = f.tool_id
GROUP BY t.tool_group, t.tool_id
ORDER BY utilization_pct DESC;

-- Q4. Yield excursion check (Process / yield engineer): weekly yield of the
-- lots etched on each tool at one step. Looking at ONE step matters: a lot
-- visits etch several times, so mixing all visits would spread a bad tool's
-- effect over the good tools too. At step 4 every lot runs exactly once.
WITH etch_lots AS (
    SELECT f.lot_id, f.tool_id, d.iso_week
    FROM fact_lot_step f
    JOIN dim_step s ON s.step_key = f.step_key
    JOIN dim_date d ON d.date = f.date
    WHERE s.step_name = 'Etch 04' AND f.tool_id <> 'UNKNOWN'
)
SELECT e.iso_week,
       e.tool_id,
       COUNT(*)                          AS lots,
       ROUND(AVG(l.die_yield_pct), 1)    AS avg_yield_pct
FROM etch_lots e
JOIN fact_lot l ON l.lot_id = e.lot_id
GROUP BY e.iso_week, e.tool_id
ORDER BY e.iso_week, e.tool_id;

-- Q5. Same question, summarised: yield of lots etched at step 4 on ETCH-03
-- in the suspect window versus all other lots.
WITH suspect AS (
    SELECT f.lot_id
    FROM fact_lot_step f
    JOIN dim_step s ON s.step_key = f.step_key
    WHERE s.step_name = 'Etch 04' AND f.tool_id = 'ETCH-03'
      AND f.date BETWEEN '2026-07-06' AND '2026-08-02'
)
SELECT CASE WHEN s.lot_id IS NULL THEN 'Other lots' ELSE 'ETCH-03 at Etch 04, 6 Jul - 2 Aug' END AS lot_group,
       COUNT(*)                            AS lots,
       ROUND(AVG(l.die_yield_pct), 1)      AS avg_yield_pct
FROM fact_lot l
LEFT JOIN suspect s ON s.lot_id = l.lot_id
GROUP BY 1;

-- Q6. WIP trend at the bottleneck, with a 7-day moving average
SELECT date,
       wip_lots,
       ROUND(AVG(wip_lots) OVER (ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 1) AS wip_7d_avg
FROM fact_wip_day
WHERE tool_group = 'LITHO'
ORDER BY date;

-- Q7. Hold analysis: why are lots stopped, and for how long?
SELECT hold_reason,
       COUNT(*)                     AS holds,
       ROUND(SUM(hold_hours))       AS total_hold_h,
       ROUND(AVG(hold_hours), 1)    AS avg_hold_h
FROM fact_lot_step
WHERE hold_reason IS NOT NULL
GROUP BY hold_reason
ORDER BY total_hold_h DESC;
