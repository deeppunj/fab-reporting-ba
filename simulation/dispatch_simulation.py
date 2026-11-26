# dispatch_simulation.py
#
# A small queue simulation of the pilot line in this repo.
# Question: when several lots wait for the same tool group, which lot should
# go first, and how does the answer change as the line gets busier?
#
# The inputs come from the repo's own data: routes, number of tools, process
# times, lot starts per day, product mix, hot-lot share, holds and the tool
# down events. The data itself is simulated, so this is a simulation of a
# simulated line.
#
# One difference to the generated data: in the generator, queue times are
# drawn from a fixed average per tool group. Here the tools have limited
# capacity, so a lot waits only when all tools of its group are busy. This
# is why the waiting times below are not the same as in the data (see the
# README next to this file).
#
# Simplifications:
# - lots of one tool group share one queue, any free tool takes the next lot
# - a tool that is due for PM or a breakdown goes down when it is next free
#   (a lot that is already running is not interrupted)
# - process times are normal with mean and sd taken from the clean data
# - a constant transport time between steps
#
# Run:  python simulation/dispatch_simulation.py
# Output: simulation/results/ (check table, summary table, chart)

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import simpy

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
CLEAN = ROOT / "data" / "clean"
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)

START = pd.Timestamp("2026-04-06")
STARTS_END_H = 150 * 24          # lots start during the first 150 days
WARMUP_H = 14 * 24               # lots started in the first 14 days are not counted
HORIZON_H = STARTS_END_H + 40 * 24   # 40 more days so late lots can finish
CHECK_DAYS = 157                 # the repo's tool-day table covers 157 days (6 Apr to 9 Sep)
REPS = 8                         # repeats with different random numbers

# ---------------------------------------------------------------------------
# 1. Inputs from the repo's data
# ---------------------------------------------------------------------------
routes = pd.read_csv(RAW / "routes.csv")
tools = pd.read_csv(RAW / "tools.csv")
products = pd.read_csv(RAW / "products.csv").set_index("product_id")
lots_in = pd.read_csv(RAW / "lots.csv", parse_dates=["start_ts"])
events = pd.read_csv(RAW / "tool_events.csv", parse_dates=["start_ts", "end_ts"])
steps = pd.read_csv(CLEAN / "fact_lot_step.csv", parse_dates=["arrive_ts", "track_out_ts"])
dim_step = pd.read_csv(CLEAN / "dim_step.csv")
tool_day = pd.read_csv(CLEAN / "fact_tool_day.csv")
fact_lot = pd.read_csv(CLEAN / "fact_lot.csv")

route = {p: g.sort_values("step_no")["tool_group"].tolist() for p, g in routes.groupby("product_id")}
n_tools = tools.groupby("tool_group").size()
group_of_tool = tools.set_index("tool_id")["tool_group"]

steps = steps[steps["dq_flag"] == "OK"].merge(dim_step[["step_key", "tool_group"]], on="step_key")
proc = steps.groupby("tool_group")["process_hours"].agg(["mean", "std"])

span_days = (lots_in["start_ts"].max() - lots_in["start_ts"].min()).total_seconds() / 86400
starts_per_day = len(lots_in) / span_days
mix = lots_in["product_id"].value_counts(normalize=True)
hot_share = (lots_in["priority"] == "HOT").mean()

hold_prob = (steps["hold_hours"] > 0).mean()
hold_mean = steps.loc[steps["hold_hours"] > 0, "hold_hours"].mean()

by_lot = steps.sort_values(["lot_id", "track_out_ts"]).copy()
by_lot["next_arrive"] = by_lot.groupby("lot_id")["arrive_ts"].shift(-1)
transport_h = ((by_lot["next_arrive"] - by_lot["track_out_ts"]).dt.total_seconds() / 3600).mean()

# down events as (group, start hour, length in hours)
down_events = []
for e in events.itertuples():
    start_h = (e.start_ts - START).total_seconds() / 3600
    length_h = (e.end_ts - e.start_ts).total_seconds() / 3600
    if 0 <= start_h < HORIZON_H:
        down_events.append((group_of_tool[e.tool_id], start_h, length_h))


# ---------------------------------------------------------------------------
# 2. Lots: drawn once per repeat, so every dispatching rule sees the same lots
# ---------------------------------------------------------------------------
def make_lots(rng, load):
    """load = 1.0 is the line as it is in the data, 1.2 is 20% more lot starts."""
    lots, t = [], 0.0
    gap_mean = 24 / (starts_per_day * load)
    while True:
        t += rng.exponential(gap_mean)
        if t > STARTS_END_H:
            break
        product = rng.choice(mix.index, p=mix.values)
        hot = rng.random() < hot_share
        lot_steps = []
        for group in route[product]:
            p = max(rng.normal(proc.loc[group, "mean"], proc.loc[group, "std"]), 0.1)
            hold = rng.gamma(2, hold_mean / 2) if rng.random() < hold_prob else 0.0
            lot_steps.append((group, p, hold))
        # hot lots have a target cycle time of 60% of the normal one (as in the data)
        target_h = products.loc[product, "target_ct_days"] * 24 * (0.6 if hot else 1.0)
        lots.append({"start": t, "hot": hot, "target_h": target_h, "steps": lot_steps})
    return lots


# ---------------------------------------------------------------------------
# 3. The simulation
# ---------------------------------------------------------------------------
def priority(rule, lot, now):
    """Lower number goes first. Lots with the same number go in order of arrival.
    A number between 0 and 1 mixes the two time-based rules: 0 is first in, first
    out, 1 is earliest due date, in between is a weighted mix of arrival and due time."""
    if isinstance(rule, float):
        return rule * (lot["start"] + lot["target_h"]) + (1 - rule) * now
    if rule == "fifo":
        return 0
    if rule == "hot_first":
        return 0 if lot["hot"] else 1
    if rule == "due_date":
        return lot["start"] + lot["target_h"]      # earliest due date first
    raise ValueError(rule)


def go_down(env, resource, start_h, length_h):
    yield env.timeout(start_h)
    with resource.request(priority=-1) as req:      # first in line, but waits for a running lot
        yield req
        yield env.timeout(length_h)


def lot_process(env, lot, lot_id, resources, rule, step_log, finish):
    yield env.timeout(lot["start"])
    for i, (group, p, hold) in enumerate(lot["steps"]):
        if i > 0:
            yield env.timeout(transport_h)
        if hold > 0:
            yield env.timeout(hold)
        arrive = env.now
        with resources[group].request(priority=priority(rule, lot, env.now)) as req:
            yield req
            track_in = env.now
            yield env.timeout(p)
        step_log.append((lot_id, group, track_in - arrive, p, track_in))
    finish[lot_id] = env.now


def run(lots, rule):
    env = simpy.Environment()
    resources = {g: simpy.PriorityResource(env, capacity=int(n)) for g, n in n_tools.items()}
    for group, start_h, length_h in down_events:
        env.process(go_down(env, resources[group], start_h, length_h))
    step_log, finish = [], {}
    for lot_id, lot in enumerate(lots):
        env.process(lot_process(env, lot, lot_id, resources, rule, step_log, finish))
    env.run(until=HORIZON_H)
    log = pd.DataFrame(step_log, columns=["lot_id", "group", "wait_h", "proc_h", "track_in_h"])
    return log, finish


# ---------------------------------------------------------------------------
# 4. Numbers from one run
# ---------------------------------------------------------------------------
def summarize(lots, log, finish):
    counted = [i for i, l in enumerate(lots) if l["start"] >= WARMUP_H]
    hot = {i for i in counted if lots[i]["hot"]}
    log = log[log["lot_id"].isin(counted)]
    litho = log[log["group"] == "LITHO"]
    done = [i for i in counted if i in finish]
    cycle_d = np.array([(finish[i] - lots[i]["start"]) / 24 for i in done])
    on_time = sum(1 for i in done if finish[i] - lots[i]["start"] <= lots[i]["target_h"])
    return {
        "litho_wait_mean_h": litho["wait_h"].mean(),
        "litho_wait_p95_h": litho["wait_h"].quantile(0.95),
        "litho_wait_hot_h": litho[litho["lot_id"].isin(hot)]["wait_h"].mean(),
        "litho_wait_normal_h": litho[~litho["lot_id"].isin(hot)]["wait_h"].mean(),
        "cycle_time_days": cycle_d.mean(),
        "on_time_pct": 100 * on_time / len(counted),     # lots not finished count as late
        "unfinished_lots": len(counted) - len(done),
    }


def utilization(log, win=(0, CHECK_DAYS * 24)):
    """Busy hours / up hours per tool group, like the SQL in the repo (Q3).
    The window is the same 157 days the repo's tool-day table covers."""
    log = log[(log["track_in_h"] >= win[0]) & (log["track_in_h"] < win[1])]
    busy = log.groupby("group")["proc_h"].sum()
    down = {}
    for group, s, length in down_events:
        overlap = max(0.0, min(s + length, win[1]) - max(s, win[0]))
        down[group] = down.get(group, 0.0) + overlap
    out = {}
    for g, n in n_tools.items():
        up = n * (win[1] - win[0]) - down.get(g, 0.0)
        out[g] = 100 * busy.get(g, 0.0) / up
    return pd.Series(out)


# ---------------------------------------------------------------------------
# 5. Check against the data (load 1.0, first in first out)
# ---------------------------------------------------------------------------
def check():
    util, wait, cycle, ontime = [], [], [], []
    for rep in range(REPS):
        lots = make_lots(np.random.default_rng(rep), 1.0)
        log, finish = run(lots, "fifo")
        util.append(utilization(log))
        counted = {i for i, l in enumerate(lots) if l["start"] >= WARMUP_H}
        wait.append(log[log["lot_id"].isin(counted)].groupby("group")["wait_h"].mean())
        s = summarize(lots, log, finish)
        cycle.append(s["cycle_time_days"])
        ontime.append(s["on_time_pct"])

    day_sums = tool_day.merge(tools[["tool_id", "tool_group"]], on="tool_id").groupby("tool_group")[["busy_hours", "up_hours"]].sum()
    data_util = 100 * day_sums["busy_hours"] / day_sums["up_hours"]
    data_wait = steps.groupby("tool_group")["queue_hours"].mean()

    table = pd.DataFrame({
        "utilization_data_pct": data_util,
        "utilization_sim_pct": pd.concat(util, axis=1).mean(axis=1),
        "wait_data_h": data_wait,
        "wait_sim_h": pd.concat(wait, axis=1).mean(axis=1),
    }).round(1).sort_values("utilization_data_pct", ascending=False)
    table.to_csv(OUT / "check_against_data.csv")
    print(table.to_string())
    print(f"\nmean cycle time (days): data {fact_lot['cycle_time_days'].mean():.1f}, simulation {np.mean(cycle):.1f}")
    print(f"lots on time (%):       data {100 * fact_lot['on_time'].mean():.1f}, simulation {np.mean(ontime):.1f}")


# ---------------------------------------------------------------------------
# 6. Dispatching rules at different loads
# ---------------------------------------------------------------------------
RULES = ["fifo", "hot_first", "due_date"]
LOADS = [0.9, 1.0, 1.05, 1.1, 1.15]


def sweep():
    rows = []
    for load in LOADS:
        for rep in range(REPS):
            lots = make_lots(np.random.default_rng(1000 + rep), load)    # same lots for all rules
            for rule in RULES:
                log, finish = run(lots, rule)
                rows.append({"load": load, "rule": rule, "rep": rep, **summarize(lots, log, finish)})
    runs = pd.DataFrame(rows)
    summary = runs.drop(columns="rep").groupby(["load", "rule"]).mean().round(2)
    summary.to_csv(OUT / "dispatch_rules_summary.csv")
    print(summary.to_string())

    fig, axes = plt.subplots(2, 2, figsize=(10, 7))
    axes = axes.ravel()
    labels = {"fifo": "first in, first out", "hot_first": "hot lots first", "due_date": "earliest due date"}
    for ax, col, title in zip(
            axes,
            ["litho_wait_normal_h", "litho_wait_hot_h", "litho_wait_p95_h", "on_time_pct"],
            ["Wait at lithography, normal lots (mean, h)", "Wait at lithography, hot lots (mean, h)",
             "Wait at lithography, all lots (95th percentile, h)", "Lots finished on time (%)"]):
        for rule in RULES:
            s = runs[runs["rule"] == rule].groupby("load")[col]
            ax.errorbar(s.mean().index, s.mean().values, yerr=s.std().values / np.sqrt(REPS), marker="o", capsize=3, label=labels[rule])
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("lot starts compared with the data (1.0 = as is)", fontsize=8)
    axes[0].legend(fontsize=8)
    fig.suptitle("Dispatching rules at lithography, simulated pilot line (mean and standard error over "
                 f"{REPS} repeats)", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "dispatch_rules.png", dpi=150)


# ---------------------------------------------------------------------------
# 7. A small search: how much weight on the due date?
# ---------------------------------------------------------------------------
# Earliest due date finishes more lots on time, but its 95th percentile wait is
# long (lots with a late due date are pushed back). The mix above gives a knob
# between first in first out (0) and earliest due date (1).
# Goal, set before looking at results: most lots on time, with the 95th
# percentile wait at lithography no longer than 20 hours, at 10% more lot starts.
# The weight is chosen on one set of random repeats and checked on another, so
# the choice is not just fitted to the numbers it was picked on.
TUNE_LOAD = 1.1
P95_LIMIT_H = 20
WEIGHTS = [round(w, 1) for w in np.arange(0, 1.01, 0.1)]


def evaluate(seed_start):
    rows = []
    for rep in range(REPS):
        lots = make_lots(np.random.default_rng(seed_start + rep), TUNE_LOAD)
        for w in WEIGHTS:
            log, finish = run(lots, float(w))
            rows.append({"weight": w, **summarize(lots, log, finish)})
    return pd.DataFrame(rows).groupby("weight")[["on_time_pct", "litho_wait_p95_h", "litho_wait_mean_h"]].mean().round(2)


def tune():
    chosen_on = evaluate(2000)       # repeats used to choose the weight
    checked_on = evaluate(3000)      # different repeats, used only to check
    ok = chosen_on[chosen_on["litho_wait_p95_h"] <= P95_LIMIT_H]
    best = ok["on_time_pct"].idxmax() if len(ok) else None
    table = chosen_on.join(checked_on, lsuffix="_choose", rsuffix="_check")
    table.to_csv(OUT / "weight_search.csv")
    print(table.to_string())
    print(f"\nchosen weight (best on time with 95th percentile wait <= {P95_LIMIT_H} h): {best}")
    if best is not None:
        print("on the other repeats:", checked_on.loc[best].to_dict())
        # paired comparison with first in first out: same lots, 16 new repeats.
        # The difference between two rules on the same lots is less noisy than
        # comparing two averages from different lots.
        gain, tail = [], []
        for rep in range(16):
            lots = make_lots(np.random.default_rng(4000 + rep), TUNE_LOAD)
            base = summarize(lots, *run(lots, 0.0))
            mixed = summarize(lots, *run(lots, float(best)))
            gain.append(mixed["on_time_pct"] - base["on_time_pct"])
            tail.append(mixed["litho_wait_p95_h"] - base["litho_wait_p95_h"])
        for name, d in [("lots on time (points)", gain), ("95th percentile wait (h)", tail)]:
            half = 1.96 * np.std(d, ddof=1) / np.sqrt(len(d))
            print(f"weight {best} against first in first out, {name}: "
                  f"{np.mean(d):+.1f} (95% interval {np.mean(d) - half:+.1f} to {np.mean(d) + half:+.1f})")

    fig, ax = plt.subplots(figsize=(6, 4.2))
    ax.plot(checked_on["litho_wait_p95_h"], checked_on["on_time_pct"], marker="o")
    for w, r in checked_on.iterrows():
        ax.annotate(f"{w:.1f}", (r["litho_wait_p95_h"], r["on_time_pct"]), textcoords="offset points", xytext=(4, 4), fontsize=8)
    ax.axvline(P95_LIMIT_H, color="grey", linestyle="--")
    ax.set_xlabel("95th percentile wait at lithography (h)")
    ax.set_ylabel("Lots finished on time (%)")
    ax.set_title("Weight on due date (0 = first in first out, 1 = earliest due date)\n"
                 "checked on separate repeats, 10% more lot starts", fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT / "weight_search.png", dpi=150)


if __name__ == "__main__":
    check()
    print()
    sweep()
    print()
    tune()
