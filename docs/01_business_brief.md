# Business brief: Pilot-line operations reporting

*Fictional case. The pilot line, people and data are simulated. The method is the one a reporting business analyst follows in a real fab.*

## 1. The problem

The pilot line runs R&D lots for internal programs and external partners. Today each team builds its own Excel report from MES exports:

- Operations counts lots out per week in one sheet, Equipment tracks tool downtime in another, and Yield engineering keeps its own list.
- The numbers do not agree. "Cycle time" means start-to-finish for one team and first-step-to-last-step for another.
- When yield dropped in July, it took weeks to link it to one etch tool, because nobody could see lot history, tool and yield in one place.
- Partners keep asking "when will my lots be ready?", and the line cannot answer with confidence.

**Problem statement:** Pilot-line decisions are slow and disputed because operational data is spread over separate reports with different definitions and no data-quality checks.

## 2. Objectives

| # | Objective | How we will know |
|---|-----------|------------------|
| O1 | One agreed definition for each operational KPI | KPI dictionary signed off by all four stakeholder groups |
| O2 | One trusted data model fed from the MES export | Star schema with automated data-quality checks; every rejected row logged |
| O3 | A dashboard people use every week | Used in the weekly line meeting instead of the Excel packs |
| O4 | Faster detection of yield excursions | Excursion visible within one week, not after several weeks |

## 3. Stakeholders

| Stakeholder | Role | What they need | Influence / interest |
|-------------|------|----------------|----------------------|
| Pilot-line operations manager | Sponsor | Output, cycle time, on-time delivery per week | High / High |
| Line / shift manager | Daily user | Where WIP is piling up today; which lots are on hold | Medium / High |
| Equipment engineering | User | Tool availability, utilization, unscheduled downtime | Medium / High |
| Process and yield engineering | User | Yield by product and by tool; excursion alerts | Medium / High |
| Program / partner managers | Consumer | Expected finish date for their lots | High / Medium |
| ICT / data engineering | Delivery partner | Clear specs for MES extracts, data model, refresh | Medium / Medium |

## 4. Scope

**In scope (v1):** lot moves, holds, tool down events and final yield from the MES export; four report pages (Line overview, Bottlenecks and WIP, Tool performance, Yield); data-quality report.

**Out of scope (v1):** real-time (sub-daily) refresh, sensor/FDC data, cost reporting, partner self-service portal. These go on the backlog.

## 5. Business questions

1. How many lots finished this week, how long did they take, and were they on time?
2. Where do lots wait the longest, and is it getting worse?
3. Which tools lose the most time to unscheduled downtime?
4. Is any tool linked to lower yield?
5. Why are lots put on hold, and for how long?

## 6. User stories (v1 backlog)

| ID | As a... | I want... | So that... | Priority |
|----|---------|-----------|------------|----------|
| US-01 | operations manager | weekly lots out, average cycle time and on-time % on one page | I can run the weekly line meeting from one source | Must |
| US-02 | line manager | WIP per tool group for each day, with a trend | I can move operators to where lots pile up | Must |
| US-03 | equipment engineer | availability and utilization per tool, split into PM and unscheduled down | I can target the tools that hurt the line most | Must |
| US-04 | yield engineer | weekly yield per etch tool | I can spot a tool excursion within a week | Must |
| US-05 | any user | to see which source rows were rejected and why | I can trust the numbers | Must |
| US-06 | line manager | hold reasons and hold hours | I can reduce avoidable holds | Should |
| US-07 | partner manager | the expected finish date of a lot | I can answer partners without calling the line | Could (v2) |

**Acceptance criteria example (US-01):**
- Given the data for week 2026-W28, the page shows lots out, average cycle time (days, 2 decimals) and on-time % (1 decimal).
- The values match `sql/03_kpi_queries.sql`, Q1, exactly.
- Filtering by product changes all three numbers consistently.

## 7. Assumptions and risks

- **Assumption:** the MES export can be delivered daily as CSV with the fields in `docs/03_data_model.md`.
- **Risk:** source data quality (duplicates, missing tool ids, wrong timestamps). **Mitigation:** automated checks with a visible data-quality page, so problems are fixed at the source rather than hidden.
- **Risk:** KPI definitions keep changing. **Mitigation:** KPI dictionary under change control; any change needs sponsor sign-off.
