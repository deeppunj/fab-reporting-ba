# KPI dictionary

One definition per KPI, agreed with the owner. Each KPI is built as a DAX measure in Power BI (`powerbi/power_bi_build_guide.md`), and `sql/03_kpi_queries.sql` must give the same numbers.

| KPI | Definition | Formula | Grain / table | Owner | Target |
|-----|------------|---------|---------------|-------|--------|
| Lots out | Lots that finished their last step in the period | `COUNT(lot_id)` by finish date | `fact_lot` | Operations manager | — |
| Cycle time (days) | Time from arrival at step 1 to track-out of the last step | `last track-out − first arrival` | `fact_lot` | Operations manager | Per product (`dim_product.target_ct_days`) |
| On-time delivery % | Share of lots finished within target cycle time | `lots with cycle time ≤ target ÷ lots out` | `fact_lot` | Operations manager | ≥ 85 % |
| X-factor | How much longer a lot takes than its pure processing time | `cycle time ÷ sum of process time` | `fact_lot` | Operations manager | ≤ 3.5 |
| Queue time (h) | Time a lot waits at a step before track-in, holds excluded | `track-in − arrival − hold hours` | `fact_lot_step` | Line manager | — |
| WIP (lots) | Lots waiting or processing at a tool group at end of day | count of lots with arrival < snapshot ≤ track-out | `fact_wip_day` | Line manager | — |
| Availability % | Share of time a tool is up | `up hours ÷ (up + PM + unscheduled down hours)` | `fact_tool_day` | Equipment engineering | ≥ 95 % |
| Utilization % | Share of up time a tool is processing | `busy hours ÷ up hours` | `fact_tool_day` | Equipment engineering | Bottleneck ≤ 85 % |
| Unscheduled downtime (h) | Hours a tool is down for breakdowns | sum of unscheduled down hours | `fact_tool_day` | Equipment engineering | — |
| Die yield % | Share of good dies at final test, averaged over lots | `AVG(die_yield_pct)` | `fact_lot` | Yield engineering | Per product (`dim_product.target_yield_pct`) |
| Hold hours | Time lots spend on hold | sum of `hold_hours` | `fact_lot_step` | Line manager | — |
| Data-quality rejects | Source rows removed or flagged by the checks | count per rule | `dq_report` | BI / data owner | 0 rejected rows hidden |

## Business rules

1. **Hot lots** have a target cycle time of 60 % of the normal product target.
2. A move with **track-out before track-in** is kept for lot counts, but its process time is left empty. It never enters an average.
3. Moves with a **missing or unknown tool id** are mapped to tool `UNKNOWN`, so lot-level KPIs stay complete while tool-level KPIs are not distorted.
4. **Exact duplicate rows** and a second row for the same lot and step are removed.
5. **Cycle time and yield** are reported on the finish date of the lot; tool hours on the calendar day they happen.
6. **WIP** is a snapshot at the end of each day (midnight).
