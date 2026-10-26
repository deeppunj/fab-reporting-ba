# Power BI model guide

How to build the Power BI version of the report from the star schema in `data/clean/`: import, relationships, DAX measures and the "Line overview" page. The measures are also in [`measures.dax`](measures.dax).

**Goal of the Line overview page (user story US-01):** the operations manager runs the weekly meeting from this one page.

---

## Step 0. Two settings before loading any data

Open Power BI Desktop → **File → Options and settings → Options**, then under **CURRENT FILE**:

1. **Regional settings → Locale for import → English (United States).**
   *Why:* the CSV files use a dot as decimal separator (4.29). With Belgian settings, Power BI reads it as 429 and every number is wrong. This is the most common silent error in Belgium.
2. **Data Load → untick "Autodetect new relationships after data is loaded".**
   *Why:* you will make the relationships yourself, so you know each one is right. Autodetect can guess wrong joins.

Save the file as `fab_reporting.pbix`.

## Step 1. Load the data

**Home → Get data → Text/CSV**, and load each file from `data/clean/`:
`dim_date`, `dim_product`, `dim_tool`, `dim_step`, `dim_lot`, `fact_lot`, `fact_lot_step`, `fact_tool_day`, `fact_wip_day`, `dq_report`.

For each file click **Transform Data** (not Load). This opens **Power Query**. Check the type icon next to each column header:

| Columns | Type |
|---------|------|
| `date`, `finish_date` | Date |
| `arrive_ts`, `track_in_ts`, `track_out_ts` | Date/Time |
| hours, days, %, x_factor | Decimal number |
| `on_time`, `wafers_*`, `wip_lots` | Whole number |
| ids and names | Text |

Then **Home → Close & Apply**.

> **Checkpoint 1:** In Table view, open `fact_lot`. Row count (bottom left) must be **609**, and `cycle_time_days` values must look like 5.28, not 528.

## Step 2. Relationships

Go to **Model view**. Drag each line from the dimension (the "1" side) to the fact (the "many" side):

| From (1) | To (many) |
|----------|-----------|
| `dim_date[date]` | `fact_lot[finish_date]` |
| `dim_date[date]` | `fact_lot_step[date]` |
| `dim_date[date]` | `fact_tool_day[date]` |
| `dim_date[date]` | `fact_wip_day[date]` |
| `dim_lot[lot_id]` | `fact_lot[lot_id]` |
| `dim_lot[lot_id]` | `fact_lot_step[lot_id]` |
| `dim_product[product_id]` | `dim_lot[product_id]` |
| `dim_step[step_key]` | `fact_lot_step[step_key]` |
| `dim_tool[tool_id]` | `fact_lot_step[tool_id]` |
| `dim_tool[tool_id]` | `fact_tool_day[tool_id]` |

Keep **cross-filter direction = Single** for all of them.

**Do not** link `dim_product` to `dim_step`. A product filter would then reach `fact_lot_step` by two roads (through `dim_lot` and through `dim_step`). Power BI does not allow that and makes one of them inactive without a clear warning. One road is enough: product → lot → step facts (no ambiguous filter paths).

Then select `dim_date` → **Table tools → Mark as date table** → column `date`.

> **Checkpoint 2:** Your model looks like a star: facts in the middle, dimensions around them. No line between two fact tables.

## Step 3. Measures

**Home → Enter data**, name the table `_Measures`, click Load. Select it, then **New measure** for each line below. Copy them exactly.

```DAX
Lots Out = COUNTROWS ( fact_lot )

Avg Cycle Time (days) = AVERAGE ( fact_lot[cycle_time_days] )

On-Time % = DIVIDE ( SUM ( fact_lot[on_time] ), COUNTROWS ( fact_lot ) )

Avg X-Factor = AVERAGE ( fact_lot[x_factor] )

Avg Yield % = AVERAGE ( fact_lot[die_yield_pct] ) / 100

Avg Queue (h) = AVERAGE ( fact_lot_step[queue_hours] )

-- share of all waiting time that happens at this tool group
Queue Share % =
DIVIDE (
    SUM ( fact_lot_step[queue_hours] ),
    CALCULATE ( SUM ( fact_lot_step[queue_hours] ), REMOVEFILTERS ( dim_step ) )
)

Availability % =
DIVIDE (
    SUM ( fact_tool_day[up_hours] ),
    SUM ( fact_tool_day[up_hours] ) + SUM ( fact_tool_day[pm_hours] ) + SUM ( fact_tool_day[unscheduled_hours] )
)

Utilization % = DIVIDE ( SUM ( fact_tool_day[busy_hours] ), SUM ( fact_tool_day[up_hours] ) )

-- WIP is a level, not a flow: never add days together.
-- For a week or month, show the value on the last day.
WIP (end of period) =
CALCULATE ( SUM ( fact_wip_day[wip_lots] ), LASTDATE ( dim_date[date] ) )

-- time intelligence: change versus the previous month
Cycle Time vs Prev Month =
[Avg Cycle Time (days)]
    - CALCULATE ( [Avg Cycle Time (days)], DATEADD ( dim_date[date], -1, MONTH ) )
```

Format: select each % measure → **Measure tools → Format → Percentage**, 1 decimal. Cycle time → Decimal, 2 decimals.

## Step 4. Build the page

Rename the page **Line overview**.

1. **Four cards** across the top: `Lots Out`, `Avg Cycle Time (days)`, `On-Time %`, `Avg Yield %`.
2. **Line and clustered column chart**: X-axis `dim_date[iso_week]`; columns `Lots Out`; line `On-Time %`. Title: *Weekly output and on-time delivery*.
3. **Clustered bar chart**: Y-axis `dim_step[tool_group]`; X-axis `Queue Share %`; sort descending. Title: *Where lots wait (share of all queue time)*.
4. **Slicers**: `dim_product[product_name]`, `dim_lot[priority]`, `dim_date[month]`.
5. **Text box** at the top: *Pilot-line operations: weekly overview (simulated data)*.

Keep it plain: one accent colour, no 3D, titles that say what the chart shows.

## Step 5. Reconcile with SQL

Same reconciliation as for the web dashboard (`docs/04_test_plan.md`). With no slicers set:

| Check | Expected (from SQL) |
|-------|---------------------|
| Lots Out (total) | 609 |
| On-Time % (total) | 72.9 % |
| Week 2026-W28: Lots Out | 28 |
| Week 2026-W28: Avg Cycle Time | 5.28 |
| Queue Share %, LITHO | 44.8 % |

If a number does not match, do not adjust the visual. Find out why (usually a data type or a relationship).

> **Checkpoint 3:** all five match.
