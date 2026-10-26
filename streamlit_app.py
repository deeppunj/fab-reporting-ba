# streamlit_app.py
#
# Interactive dashboard for the pilot-line fab reporting project.
# It reads the star schema in data/clean/ (built by python/02_...py).
#
# Run on your computer:   streamlit run streamlit_app.py
#
# Every number is calculated the same way as in sql/03_kpi_queries.sql,
# so the app can be checked against SQL (see docs/04_test_plan.md).

from pathlib import Path

import pandas as pd
import streamlit as st

DATA = Path(__file__).parent / "data" / "clean"
GITHUB = "https://github.com/deeppunj/fab-reporting-ba"

ON_TIME_TARGET = 85                       # % of lots that should finish within their target cycle time
EXCURSION_TOOL = "ETCH-03"                # the tool under suspicion
EXCURSION_START, EXCURSION_END = "2026-07-06", "2026-08-02"

BLUE = "#2a78d6"
GREY = "#898781"
ETCH_COLOURS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]   # ETCH-01, -02, -03, -04

st.set_page_config(page_title="Pilot-Line Fab Reporting", layout="wide")


@st.cache_data
def load(name, dates=None):
    return pd.read_csv(DATA / f"{name}.csv", parse_dates=dates)


fact_lot = load("fact_lot", ["finish_date"])
fact_step = load("fact_lot_step", ["date"])
dim_lot = load("dim_lot")
dim_step = load("dim_step")
dim_product = load("dim_product")
dim_tool = load("dim_tool")
tool_day = load("fact_tool_day")
dq_report = load("dq_report")

# Lots with their product, priority and the ISO week they finished in
lots = (fact_lot
        .merge(dim_lot[["lot_id", "product_id", "priority"]], on="lot_id")
        .merge(dim_product[["product_id", "product_name"]], on="product_id"))
lots["week"] = lots["finish_date"].dt.strftime("%G-W%V")
all_weeks = sorted(lots["week"].unique())

# Lot steps with the step name, tool group, product and priority
steps = (fact_step
         .merge(dim_step[["step_key", "step_name", "tool_group"]], on="step_key")
         .merge(lots[["lot_id", "product_name", "priority", "die_yield_pct"]], on="lot_id"))

# ---------------------------------------------------------------- header and filters
st.title("Pilot-line operations reporting")
st.caption(f"Weekly view of output, cycle time, bottlenecks, tools and yield · April to October 2026 · "
           f"simulated data · [project on GitHub]({GITHUB})")

col_product, col_priority, _ = st.columns([2, 2, 4])
product = col_product.selectbox("Product", ["All"] + dim_product["product_name"].tolist())
priority = col_priority.selectbox("Priority", ["All", "NORMAL", "HOT"])


def apply_filters(df):
    """Keep only the rows that match the product and priority filters."""
    if product != "All":
        df = df[df["product_name"] == product]
    if priority != "All":
        df = df[df["priority"] == priority]
    return df


lots_f = apply_filters(lots)
steps_f = apply_filters(steps)

# ---------------------------------------------------------------- KPI tiles
on_time_pct = lots_f["on_time"].mean() * 100

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Lots out", f"{len(lots_f):,}")
k2.metric("Avg cycle time", f"{lots_f['cycle_time_days'].mean():.2f} d")
k3.metric("On-time delivery", f"{on_time_pct:.1f} %",
          delta=f"{on_time_pct - ON_TIME_TARGET:+.1f} pts vs {ON_TIME_TARGET} % target")
k4.metric("Avg X-factor", f"{lots_f['x_factor'].mean():.2f}", help="Cycle time ÷ pure process time")
k5.metric("Avg die yield", f"{lots_f['die_yield_pct'].mean():.1f} %")

# ---------------------------------------------------------------- weekly output and on-time
weekly = (lots_f.groupby("week")
          .agg(lots_out=("lot_id", "count"), on_time=("on_time", "mean"))
          .reindex(all_weeks))                      # keep every week on the axis, even if empty
weekly["lots_out"] = weekly["lots_out"].fillna(0).astype(int)
weekly["on_time"] = weekly["on_time"] * 100

left, right = st.columns(2)
with left:
    st.subheader("Lots out per week")
    st.caption(f"{len(lots_f)} lots in {len(all_weeks)} weeks; busiest week {weekly['lots_out'].idxmax()}.")
    st.bar_chart(weekly["lots_out"].rename("Lots out"), color=BLUE)
with right:
    st.subheader("On-time delivery per week")
    weeks_with_lots = int(weekly["on_time"].notna().sum())
    weeks_below = int((weekly["on_time"] < ON_TIME_TARGET).sum())
    st.caption(f"{on_time_pct:.1f} % on time overall; {weeks_below} of {weeks_with_lots} weeks below the "
               f"{ON_TIME_TARGET} % target (grey line).")
    chart = pd.DataFrame({"On-time %": weekly["on_time"], f"Target {ON_TIME_TARGET} %": ON_TIME_TARGET})
    st.line_chart(chart, color=[BLUE, GREY])

with st.expander("Weekly numbers"):
    st.dataframe(weekly.rename(columns={"lots_out": "Lots out", "on_time": "On-time %"}).round(1))

# ---------------------------------------------------------------- bottleneck
st.subheader("Where lots wait: share of all queue time")
queue = (steps_f.groupby("tool_group")
         .agg(queue_hours=("queue_hours", "sum"), visits=("queue_hours", "size"),
              avg_queue_h=("queue_hours", "mean"))
         .sort_values("queue_hours", ascending=False))
queue["share_pct"] = queue["queue_hours"] / queue["queue_hours"].sum() * 100
top = queue.index[0]
st.caption(f"{top} is the bottleneck: {queue.loc[top, 'share_pct']:.1f} % of all waiting happens in front of it.")
st.dataframe(
    queue.reset_index()[["tool_group", "share_pct", "queue_hours", "visits", "avg_queue_h"]],
    hide_index=True,
    column_config={
        "tool_group": "Tool group",
        "share_pct": st.column_config.ProgressColumn("Share of queue time", format="%.1f %%", min_value=0, max_value=100),
        "queue_hours": st.column_config.NumberColumn("Queue hours", format="%.0f"),
        "visits": "Lot visits",
        "avg_queue_h": st.column_config.NumberColumn("Avg wait per visit (h)", format="%.1f"),
    },
)

# ---------------------------------------------------------------- yield excursion
st.subheader("Die yield by etch tool at step Etch 04, per week")
# One step only: a lot visits etch several times, so mixing all visits would
# spread a bad tool's effect over the good tools. At Etch 04 each lot runs once.
etch = steps_f[(steps_f["step_name"] == "Etch 04") & (steps_f["tool_id"] != "UNKNOWN")].copy()
etch["week"] = etch["date"].dt.strftime("%G-W%V")
yield_by_tool = etch.pivot_table(index="week", columns="tool_id", values="die_yield_pct", aggfunc="mean")

suspect = etch[(etch["tool_id"] == EXCURSION_TOOL)
               & (etch["date"] >= EXCURSION_START) & (etch["date"] <= EXCURSION_END)]["lot_id"]
hit = lots_f[lots_f["lot_id"].isin(suspect)]["die_yield_pct"]
rest = lots_f[~lots_f["lot_id"].isin(suspect)]["die_yield_pct"]
if len(hit):
    st.caption(f"Lots etched on {EXCURSION_TOOL} between 6 Jul and 2 Aug (W28–W31) yielded {hit.mean():.1f} % "
               f"vs {rest.mean():.1f} % for all other lots.")
else:
    st.caption("No lots in the excursion window for this selection.")
st.line_chart(yield_by_tool, color=ETCH_COLOURS[: yield_by_tool.shape[1]], y_label="Die yield (%)")

with st.expander("Weekly yield per etch tool"):
    st.dataframe(yield_by_tool.round(1))

# ---------------------------------------------------------------- equipment
st.subheader("Equipment")
st.caption("All products: tools are shared, so the filters do not apply here. Sorted by utilization.")
tools = tool_day.groupby("tool_id")[["up_hours", "pm_hours", "unscheduled_hours", "busy_hours"]].sum()
tools = tools.join(dim_tool.set_index("tool_id"))
tools["availability"] = tools["up_hours"] / (tools["up_hours"] + tools["pm_hours"] + tools["unscheduled_hours"]) * 100
tools["utilization"] = tools["busy_hours"] / tools["up_hours"] * 100
st.dataframe(
    tools.sort_values("utilization", ascending=False).reset_index()
         [["tool_id", "tool_group", "availability", "utilization", "unscheduled_hours", "pm_hours"]],
    hide_index=True,
    column_config={
        "tool_id": "Tool",
        "tool_group": "Group",
        "availability": st.column_config.NumberColumn("Availability %", format="%.1f"),
        "utilization": st.column_config.ProgressColumn("Utilization", format="%.1f %%", min_value=0, max_value=100),
        "unscheduled_hours": st.column_config.NumberColumn("Unscheduled down (h)", format="%.1f"),
        "pm_hours": st.column_config.NumberColumn("Planned maintenance (h)", format="%.1f"),
    },
)

# ---------------------------------------------------------------- data quality
st.subheader("Data quality")
st.caption("Every check run on the MES export before reporting. Nothing is removed without being counted here.")
st.dataframe(dq_report.rename(columns={"rule": "Check", "rows_affected": "Rows", "action": "Action"}), hide_index=True)

st.caption("Fab MES data is never public, so the data is simulated with the structure of a real fab "
           f"(re-entrant routes, downtime, hot lots, holds, yield). Source: [{GITHUB}]({GITHUB})")
