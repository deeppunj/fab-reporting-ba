# 02_clean_and_build_star_schema.py
#
# Takes the raw export in data/raw/, checks it, fixes what can be fixed,
# and writes a star schema (Kimball style) to data/clean/:
#
#   dimensions: dim_date, dim_product, dim_tool, dim_step, dim_lot
#   facts:      fact_lot_step  - one row per lot per process step
#               fact_lot       - one row per finished lot (cycle time, yield, on time)
#               fact_tool_day  - one row per tool per day (up, down, busy hours)
#               fact_wip_day   - one row per tool group per day (lots waiting or running)
#
# Every check is written to data/clean/dq_report.csv, so the business can
# see what was wrong with the source data and what was done about it.

import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
CLEAN = ROOT / "data" / "clean"
CLEAN.mkdir(parents=True, exist_ok=True)

ts = lambda cols: {"parse_dates": cols}
tools = pd.read_csv(RAW / "tools.csv")
products = pd.read_csv(RAW / "products.csv")
routes = pd.read_csv(RAW / "routes.csv")
events = pd.read_csv(RAW / "tool_events.csv", **ts(["start_ts", "end_ts"]))
lots = pd.read_csv(RAW / "lots.csv", **ts(["start_ts"]))
moves = pd.read_csv(RAW / "lot_moves.csv", **ts(["arrive_ts", "track_in_ts", "track_out_ts"]))
lot_yield = pd.read_csv(RAW / "lot_yield.csv")

dq = []   # data-quality log: one line per rule


def log(rule, rows, action):
    dq.append({"rule": rule, "rows_affected": int(rows), "action": action})


# ---------------------------------------------------------------------------
# 1. Data-quality checks on lot moves
# ---------------------------------------------------------------------------
n_raw = len(moves)

# rule 1: the same move exported twice
dups = moves.duplicated()
log("Duplicate move rows", dups.sum(), "Removed")
moves = moves[~dups].copy()

# rule 1b: a lot can pass each step only once (business key = lot + step).
# If there are two rows, keep the one that has a tool id.
moves = moves.sort_values(["lot_id", "step_no", "tool_id"], na_position="last")
key_dups = moves.duplicated(["lot_id", "step_no"])
log("Same lot and step twice (business key)", key_dups.sum(), "Removed; kept the row with a tool id")
moves = moves[~key_dups].copy()

# rule 2: tool id is empty
missing = moves["tool_id"].isna()
log("Missing tool id", missing.sum(), "Kept; tool set to UNKNOWN")

# rule 3: tool id not in the tool master list
unknown = ~moves["tool_id"].isin(tools["tool_id"]) & ~missing
log("Tool id not in tool master", unknown.sum(), "Kept; tool set to UNKNOWN")
moves.loc[missing | unknown, "tool_id"] = "UNKNOWN"

# rule 4: track-out before track-in (impossible)
neg = moves["track_out_ts"] < moves["track_in_ts"]
log("Track-out before track-in", neg.sum(), "Kept; process time left empty")

moves["dq_flag"] = "OK"
moves.loc[missing | unknown, "dq_flag"] = "UNKNOWN_TOOL"
moves.loc[neg, "dq_flag"] = "BAD_TIMESTAMP"
log("Total raw move rows", n_raw, "Input")
log("Clean move rows", len(moves), "Output")

# ---------------------------------------------------------------------------
# 2. Dimensions
# ---------------------------------------------------------------------------
# Kimball habit: an "Unknown" member, so facts never point at nothing.
dim_tool = pd.concat([tools, pd.DataFrame([{"tool_id": "UNKNOWN", "tool_group": "UNKNOWN", "bay": "UNKNOWN"}])],
                     ignore_index=True)
dim_product = products.copy()

dim_step = routes.copy()
dim_step.insert(0, "step_key", dim_step["product_id"] + "-" + dim_step["step_no"].astype(str).str.zfill(2))

dates = pd.date_range(moves["arrive_ts"].min().normalize(), moves["track_out_ts"].max().normalize(), freq="D")
dim_date = pd.DataFrame({"date": dates})
dim_date["year"] = dim_date["date"].dt.year
dim_date["month"] = dim_date["date"].dt.strftime("%Y-%m")
dim_date["iso_week"] = dim_date["date"].dt.strftime("%G-W%V")
dim_date["weekday"] = dim_date["date"].dt.day_name()

dim_lot = lots[["lot_id", "product_id", "priority", "wafers_start"]].copy()

# ---------------------------------------------------------------------------
# 3. fact_lot_step: one row per lot per step
# ---------------------------------------------------------------------------
hours = lambda a, b: (b - a).dt.total_seconds() / 3600

f = moves.merge(lots[["lot_id", "product_id"]], on="lot_id")
f["step_key"] = f["product_id"] + "-" + f["step_no"].astype(str).str.zfill(2)
f["date"] = f["track_out_ts"].dt.normalize()
f["queue_hours"] = (hours(f["arrive_ts"], f["track_in_ts"]) - f["hold_hours"]).round(2)
f["process_hours"] = hours(f["track_in_ts"], f["track_out_ts"]).round(2)
f.loc[f["dq_flag"] == "BAD_TIMESTAMP", "process_hours"] = None
f["step_cycle_hours"] = hours(f["arrive_ts"], f["track_out_ts"]).round(2)
f.loc[f["dq_flag"] == "BAD_TIMESTAMP", "step_cycle_hours"] = None

fact_lot_step = f[["lot_id", "step_key", "tool_id", "date", "arrive_ts", "track_in_ts", "track_out_ts",
                   "queue_hours", "hold_hours", "hold_reason", "process_hours", "step_cycle_hours", "dq_flag"]]

# ---------------------------------------------------------------------------
# 4. fact_lot: one row per lot
# ---------------------------------------------------------------------------
per_lot = f.groupby("lot_id").agg(first_arrive=("arrive_ts", "min"),
                                  last_out=("track_out_ts", "max"),
                                  raw_process_hours=("process_hours", "sum"),
                                  hold_hours=("hold_hours", "sum"))
fact_lot = (lots.merge(per_lot, on="lot_id")
                .merge(lot_yield, on="lot_id")
                .merge(products[["product_id", "target_ct_days"]], on="product_id"))

fact_lot["finish_date"] = fact_lot["last_out"].dt.normalize()
fact_lot["cycle_time_days"] = ((fact_lot["last_out"] - fact_lot["first_arrive"]).dt.total_seconds() / 86400).round(2)
# X-factor = cycle time / pure process time. 1.0 would mean no waiting at all.
fact_lot["x_factor"] = (fact_lot["cycle_time_days"] * 24 / fact_lot["raw_process_hours"]).round(2)
# business rule: hot lots get 60% of the normal target cycle time
fact_lot["target_ct_days"] = fact_lot["target_ct_days"].where(fact_lot["priority"] == "NORMAL",
                                                              fact_lot["target_ct_days"] * 0.6).round(2)
fact_lot["on_time"] = (fact_lot["cycle_time_days"] <= fact_lot["target_ct_days"]).astype(int)

fact_lot = fact_lot[["lot_id", "finish_date", "cycle_time_days", "target_ct_days", "on_time", "x_factor",
                     "raw_process_hours", "hold_hours", "wafers_start", "wafers_out", "die_yield_pct"]]

# ---------------------------------------------------------------------------
# 5. fact_tool_day: hours per tool per day
# ---------------------------------------------------------------------------
# Down hours: split each down event over the days it covers.
rows = []
for ev in events.itertuples():
    for day in pd.date_range(ev.start_ts.normalize(), ev.end_ts.normalize(), freq="D"):
        s = max(ev.start_ts, day)
        e = min(ev.end_ts, day + pd.Timedelta(days=1))
        if e > s:
            rows.append({"tool_id": ev.tool_id, "date": day, "event_type": ev.event_type,
                         "hours": (e - s).total_seconds() / 3600})
down = (pd.DataFrame(rows).pivot_table(index=["tool_id", "date"], columns="event_type",
                                       values="hours", aggfunc="sum", fill_value=0)
          .rename(columns={"PM": "pm_hours", "UNSCHEDULED": "unscheduled_hours"}))

# Busy hours: process time, counted on the day the lot was tracked in.
busy = (f[(f["tool_id"] != "UNKNOWN") & f["process_hours"].notna()]
        .assign(date=lambda d: d["track_in_ts"].dt.normalize())
        .groupby(["tool_id", "date"])["process_hours"].sum().rename("busy_hours"))

grid = pd.MultiIndex.from_product([tools["tool_id"], dim_date["date"]], names=["tool_id", "date"])
fact_tool_day = pd.DataFrame(index=grid).join(down).join(busy).fillna(0)
for c in ["pm_hours", "unscheduled_hours"]:
    if c not in fact_tool_day:
        fact_tool_day[c] = 0.0
fact_tool_day["busy_hours"] = fact_tool_day["busy_hours"].clip(upper=24)
fact_tool_day["up_hours"] = (24 - fact_tool_day["pm_hours"] - fact_tool_day["unscheduled_hours"]).clip(lower=0)
fact_tool_day["busy_hours"] = fact_tool_day[["busy_hours", "up_hours"]].min(axis=1)
fact_tool_day["idle_hours"] = fact_tool_day["up_hours"] - fact_tool_day["busy_hours"]
fact_tool_day = fact_tool_day.round(2).reset_index()

# ---------------------------------------------------------------------------
# 6. fact_wip_day: how many lots sit at each tool group at midnight
# ---------------------------------------------------------------------------
g = f.merge(dim_step[["step_key", "tool_group"]], on="step_key")
wip_rows = []
for day in dim_date["date"]:
    snap = day + pd.Timedelta(days=1)                  # end of that day
    at = g[(g["arrive_ts"] < snap) & (g["track_out_ts"] >= snap)]
    for grp, n in at.groupby("tool_group")["lot_id"].nunique().items():
        wip_rows.append({"date": day, "tool_group": grp, "wip_lots": n})
fact_wip_day = pd.DataFrame(wip_rows)

# ---------------------------------------------------------------------------
# 7. Referential checks (every fact key must exist in its dimension)
# ---------------------------------------------------------------------------
log("fact_lot_step tool not in dim_tool", (~fact_lot_step["tool_id"].isin(dim_tool["tool_id"])).sum(), "Must be 0")
log("fact_lot_step step not in dim_step", (~fact_lot_step["step_key"].isin(dim_step["step_key"])).sum(), "Must be 0")
log("fact_lot lot without yield", fact_lot["die_yield_pct"].isna().sum(), "Must be 0")

# ---------------------------------------------------------------------------
# 8. Save
# ---------------------------------------------------------------------------
tables = {"dim_date": dim_date, "dim_product": dim_product, "dim_tool": dim_tool, "dim_step": dim_step,
          "dim_lot": dim_lot, "fact_lot_step": fact_lot_step, "fact_lot": fact_lot,
          "fact_tool_day": fact_tool_day, "fact_wip_day": fact_wip_day,
          "dq_report": pd.DataFrame(dq)}
for name, df in tables.items():
    df.to_csv(CLEAN / f"{name}.csv", index=False, date_format="%Y-%m-%d %H:%M:%S")
    print(f"{name:15s} {len(df):6d} rows")

print()
print(pd.DataFrame(dq).to_string(index=False))
