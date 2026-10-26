# 01_generate_pilot_line_data.py
#
# Makes a SIMULATED data set for a small semiconductor pilot line.
# Real fab data (MES lot history, tool states) is never public, so I
# simulate it. The structure follows how a fab works: lots of wafers move
# through a route of process steps, each step runs on a tool, tools go
# down for maintenance, and at the end the lot gets a yield.
#
# Two "stories" are built into the data on purpose, so the dashboard has
# something real to find:
#   1. Lithography is the bottleneck: lots wait longest in front of it.
#   2. Etch tool ETCH-03 drifts for four weeks in July at the first etch
#      step of the route (step 4, "Etch 04"): lots etched there on ETCH-03
#      in that window come out with lower yield. Real excursions are usually
#      tied to one step (one recipe), not to every visit of a tool.
#
# A few data-quality problems are also added (duplicates, missing tool ids,
# wrong timestamps, an unknown tool). Script 02 has to find and fix them,
# like a real reporting analyst would.
#
# Output: CSV files in data/raw/

import numpy as np
import pandas as pd
from pathlib import Path

rng = np.random.default_rng(42)          # fixed seed, so every run gives the same data
OUT = Path(__file__).resolve().parent.parent / "data" / "raw"
OUT.mkdir(parents=True, exist_ok=True)

START = pd.Timestamp("2026-04-06")       # a Monday
END = pd.Timestamp("2026-10-04")         # 26 weeks of operation

# ---------------------------------------------------------------------------
# 1. Tool groups and tools
# ---------------------------------------------------------------------------
# name: (number of tools, mean process hours, mean queue hours)
# Litho has few tools and a long queue -> it is the bottleneck.
tool_groups = {
    "LITHO":      (2, 2.2, 9.0),
    "ETCH":       (4, 1.2, 3.0),
    "DEPOSITION": (3, 2.0, 3.5),
    "CMP":        (2, 1.0, 2.5),
    "IMPLANT":    (2, 0.8, 2.0),
    "CLEAN":      (3, 0.5, 1.0),
    "FURNACE":    (2, 4.0, 4.0),
    "METROLOGY":  (3, 0.4, 1.5),
}

tools = []
for group, (n_tools, _, _) in tool_groups.items():
    for i in range(1, n_tools + 1):
        tools.append({
            "tool_id": f"{group[:4]}-{i:02d}",      # e.g. ETCH-03
            "tool_group": group,
            "bay": f"BAY-{list(tool_groups).index(group) + 1}",
        })
tools = pd.DataFrame(tools)

# ---------------------------------------------------------------------------
# 2. Products and their routes (the ordered list of steps)
# ---------------------------------------------------------------------------
# A real route visits the same tool groups many times ("re-entrant flow").
# I build each route from a repeating module: clean -> deposit -> litho ->
# etch -> metrology, plus some product-specific steps.
products = pd.DataFrame([
    # target cycle time = days a normal lot is allowed from start to finish
    {"product_id": "P-LOGIC", "product_name": "Logic test vehicle",  "technology": "CMOS",          "target_yield_pct": 88, "target_ct_days": 7.0},
    {"product_id": "P-SIPH",  "product_name": "Si photonics MPW",    "technology": "Si photonics",  "target_yield_pct": 85, "target_ct_days": 5.5},
    {"product_id": "P-3DI",   "product_name": "3D integration",      "technology": "3D stacking",   "target_yield_pct": 80, "target_ct_days": 5.5},
])

module = ["CLEAN", "DEPOSITION", "LITHO", "ETCH", "METROLOGY"]
extra = {
    "P-LOGIC": ["IMPLANT", "FURNACE", "CMP"],
    "P-SIPH":  ["FURNACE", "CMP"],
    "P-3DI":   ["CMP", "DEPOSITION", "CMP"],
}
n_modules = {"P-LOGIC": 5, "P-SIPH": 4, "P-3DI": 4}

route_rows = []
for pid in products["product_id"]:
    steps = []
    for m in range(n_modules[pid]):
        steps += module
        if m < len(extra[pid]):
            steps.append(extra[pid][m])
    for step_no, group in enumerate(steps, start=1):
        route_rows.append({
            "product_id": pid,
            "step_no": step_no,
            "step_name": f"{group.title()} {step_no:02d}",
            "tool_group": group,
        })
routes = pd.DataFrame(route_rows)

# ---------------------------------------------------------------------------
# 3. Tool down events (planned maintenance and unscheduled breakdowns)
# ---------------------------------------------------------------------------
events = []
for tool_id in tools["tool_id"]:
    # planned maintenance (PM): about every two weeks, 6 hours
    t = START + pd.Timedelta(days=int(rng.integers(0, 14)))
    while t < END:
        events.append({"tool_id": tool_id, "event_type": "PM",
                       "start_ts": t, "end_ts": t + pd.Timedelta(hours=6)})
        t += pd.Timedelta(days=14)
    # unscheduled downs: random, a few per tool over the 26 weeks
    for _ in range(rng.poisson(4)):
        s = START + pd.Timedelta(hours=float(rng.uniform(0, (END - START).total_seconds() / 3600)))
        events.append({"tool_id": tool_id, "event_type": "UNSCHEDULED",
                       "start_ts": s, "end_ts": s + pd.Timedelta(hours=float(rng.gamma(2, 4)))})
tool_events = pd.DataFrame(events).sort_values(["tool_id", "start_ts"]).reset_index(drop=True)

# ---------------------------------------------------------------------------
# 4. Lots and their moves through the route
# ---------------------------------------------------------------------------
# Lots start every few hours. About 10% are "hot lots" (urgent), which
# wait less in each queue.
EXCURSION_TOOL = "ETCH-03"
EXCURSION_STEP = 4                       # first etch step in every route
EXCURSION_FROM = pd.Timestamp("2026-07-06")
EXCURSION_TO = pd.Timestamp("2026-08-03")

# down events per tool, for a quick "is this tool down right now?" check
down_by_tool = {tid: list(zip(g["start_ts"], g["end_ts"]))
                for tid, g in tool_events.groupby("tool_id")}

lots, moves = [], []
lot_start = START
lot_no = 0
while lot_start < END - pd.Timedelta(days=30):        # leave time for lots to finish
    lot_no += 1
    lot_id = f"L{lot_no:05d}"
    product_id = rng.choice(products["product_id"], p=[0.45, 0.35, 0.20])
    priority = "HOT" if rng.random() < 0.10 else "NORMAL"
    wafers = int(rng.choice([13, 25], p=[0.3, 0.7]))
    lots.append({"lot_id": lot_id, "product_id": product_id, "priority": priority,
                 "wafers_start": wafers, "start_ts": lot_start})

    t = lot_start
    for step in routes[routes["product_id"] == product_id].itertuples():
        n_tools, proc_mean, queue_mean = tool_groups[step.tool_group]
        group_tools = tools.loc[tools["tool_group"] == step.tool_group, "tool_id"].tolist()
        tool_id = rng.choice(group_tools)

        queue_h = rng.exponential(queue_mean) * (0.4 if priority == "HOT" else 1.0)
        proc_h = rng.normal(proc_mean, proc_mean * 0.1)

        # a lot on hold (engineering check, excursion review) waits extra
        hold_h = 0.0
        hold_reason = None
        if rng.random() < 0.02:
            hold_reason = rng.choice(["Engineering review", "Metrology out of spec", "Tool issue"])
            hold_h = rng.gamma(2, 6)

        arrive = t
        track_in = arrive + pd.Timedelta(hours=queue_h + hold_h)
        # if the tool is down at that moment, the lot waits until it is back up
        for ev in down_by_tool[tool_id]:
            if ev[0] <= track_in < ev[1]:
                track_in = ev[1]
        track_out = track_in + pd.Timedelta(hours=max(proc_h, 0.1))
        moves.append({"lot_id": lot_id, "step_no": step.step_no, "tool_id": tool_id,
                      "arrive_ts": arrive, "track_in_ts": track_in, "track_out_ts": track_out,
                      "hold_hours": round(hold_h, 2), "hold_reason": hold_reason})
        t = track_out + pd.Timedelta(minutes=float(rng.uniform(5, 30)))   # transport to next tool

    lot_start += pd.Timedelta(hours=float(rng.exponential(6)))

lots = pd.DataFrame(lots)
moves = pd.DataFrame(moves)

# ---------------------------------------------------------------------------
# 5. Yield per lot (measured at final test)
# ---------------------------------------------------------------------------
# Base yield comes from the product. Lots etched at step 4 on ETCH-03
# during the excursion window lose about 12 percentage points.
hit = moves[(moves["tool_id"] == EXCURSION_TOOL)
            & (moves["step_no"] == EXCURSION_STEP)
            & (moves["track_in_ts"] >= EXCURSION_FROM)
            & (moves["track_in_ts"] < EXCURSION_TO)]["lot_id"].unique()

base = {"P-LOGIC": 89, "P-SIPH": 86, "P-3DI": 81}
yield_rows = []
for lot in lots.itertuples():
    y = rng.normal(base[lot.product_id], 2.5)
    if lot.lot_id in hit:
        y -= rng.normal(12, 3)
    scrapped = int(rng.random() < 0.03)                 # sometimes one wafer breaks
    yield_rows.append({"lot_id": lot.lot_id,
                       "wafers_out": lot.wafers_start - scrapped,
                       "die_yield_pct": round(float(np.clip(y, 40, 99)), 1)})
lot_yield = pd.DataFrame(yield_rows)

# ---------------------------------------------------------------------------
# 6. Add some data-quality problems on purpose
# ---------------------------------------------------------------------------
# These are the kind of problems an MES export really has.
dirty = moves.copy()
# a) duplicated rows (the same move exported twice)
dirty = pd.concat([dirty, dirty.sample(40, random_state=1)])
# b) missing tool id
dirty.loc[dirty.sample(25, random_state=2).index, "tool_id"] = None
# c) track-out before track-in (clock or typing error)
bad = dirty.sample(15, random_state=3).index
dirty.loc[bad, "track_out_ts"] = dirty.loc[bad, "track_in_ts"] - pd.Timedelta(hours=1)
# d) a tool id that does not exist in the tool list
dirty.loc[dirty.sample(10, random_state=4).index, "tool_id"] = "ETCH-9"

# ---------------------------------------------------------------------------
# 7. Save
# ---------------------------------------------------------------------------
# round all timestamps to whole seconds (MES exports do not have nanoseconds)
for df in (tool_events, lots, dirty):
    for col in df.columns:
        if col.endswith("_ts"):
            df[col] = pd.to_datetime(df[col]).dt.round("s")

tools.to_csv(OUT / "tools.csv", index=False)
products.to_csv(OUT / "products.csv", index=False)
routes.to_csv(OUT / "routes.csv", index=False)
tool_events.to_csv(OUT / "tool_events.csv", index=False)
lots.to_csv(OUT / "lots.csv", index=False)
dirty.sort_values(["lot_id", "step_no"]).to_csv(OUT / "lot_moves.csv", index=False)
lot_yield.to_csv(OUT / "lot_yield.csv", index=False)

print(f"lots: {len(lots)}, moves: {len(dirty)}, tools: {len(tools)}, "
      f"tool events: {len(tool_events)}, lots hit by excursion: {len(hit)}")
