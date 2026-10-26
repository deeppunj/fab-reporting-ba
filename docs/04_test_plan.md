# Test plan and UAT script

A report is released only when the numbers are proven right and the users confirm it answers their question.

## 1. Data tests (run on every refresh)

| ID | Test | Expected | Result |
|----|------|----------|--------|
| DT-01 | Every fact row points to an existing dimension row | 0 orphans (foreign keys enforced in PostgreSQL) | Pass |
| DT-02 | Every lot has a yield | 0 missing | Pass |
| DT-03 | Duplicates removed and logged | Count in `dq_report` | Pass: 40 removed |
| DT-04 | Unknown / missing tool ids mapped to `UNKNOWN` | Count in `dq_report` | Pass: 34 rows |
| DT-05 | Bad timestamps excluded from time averages | `process_hours` empty for flagged rows | Pass: 15 rows |
| DT-06 | Tool hours per day add up to 24 | `up + PM + unscheduled = 24` | Pass |

## 2. Reconciliation (dashboard vs SQL)

The Streamlit dashboard reads the same star schema but calculates every number independently in pandas. Each headline number must equal the SQL result.

| ID | Number | SQL | Dashboard | Result |
|----|--------|-----|-----------|--------|
| RT-01 | Lots out (all) | Q1 total: 609 | 609 | Pass |
| RT-02 | On-time % (all) | 72.9 % | 72.9 % | Pass |
| RT-03 | Average die yield (all) | 85.6 % | 85.6 % | Pass |
| RT-04 | LITHO share of all queue time | Q2: 44.8 % | 44.8 % | Pass |
| RT-05 | Yield, ETCH-03 at Etch 04 in 6 Jul – 2 Aug vs other lots | Q5: 75.8 % vs 86.1 % (27 lots) | 75.8 % vs 86.1 % | Pass |
| RT-06 | Week 2026-W28: lots out and average cycle time | Q1: 28 lots, 5.28 d | 28 lots, 5.28 d | Pass |

## 3. UAT script

Each user story is accepted by the stakeholder who asked for it, by running this scenario on the dashboard.

| ID | User story | Tester | Scenario | Expected result |
|----|------------|--------|----------|-----------------|
| UAT-01 | US-01 | Operations manager | Opens the dashboard and reads this week's output and on-time delivery | Tiles and weekly charts answer the weekly-meeting questions without Excel |
| UAT-02 | US-02 | Line manager | Finds where lots wait longest | Bottleneck chart shows LITHO first, 44.8 % |
| UAT-03 | US-03 | Equipment engineer | Lists the 3 tools with most unscheduled downtime | FURN-01, IMPL-01, METR-03 from the Equipment table |
| UAT-04 | US-04 | Yield engineer | Spots the excursion from the weekly etch-tool chart | ETCH-03 drop in W28–W31, other tools flat |
| UAT-05 | US-05 | Any user | Explains why rows were removed or flagged | Data-quality table lists each rule and count |
