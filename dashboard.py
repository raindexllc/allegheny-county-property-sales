"""Read-only local dashboard over the pipeline's validated analytical output."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from sales_pipeline.model import current_generation

ROOT = Path(__file__).resolve().parent
COLORS = {"All priced transfers": "#A35B24", "Eligible market sales": "#137D8A"}

st.set_page_config(page_title="Allegheny County · What counts as a sale?", page_icon="📊", layout="wide")


@st.cache_data(show_spinner=False)
def load_publication(directory: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    path = Path(directory)
    report = json.loads((path / "run_report.json").read_text())
    content = (path / "municipality_year.csv").read_bytes()
    if hashlib.sha256(content).hexdigest() != report["output_sha256"]:
        raise ValueError("Analytical CSV does not match its validated run report")
    if any(check["violations"] for check in report["checks"]):
        raise ValueError("Publication contains failing quality checks")
    return pd.read_csv(path / "municipality_year.csv"), pd.read_csv(path / "source_reconciliation.csv"), report


def dollars(value: float) -> str:
    return "Unavailable" if pd.isna(value) else f"${value:,.0f}"


def price_chart(frame: pd.DataFrame, x: str, title: str, height: int = 310) -> alt.Chart:
    long = frame.melt(
        id_vars=[x, "eligible_market_sales", "recorded_transfers"],
        value_vars=["median_recorded_price", "median_market_price"],
        var_name="series", value_name="Median price",
    )
    long["Series"] = long["series"].map({
        "median_recorded_price": "All priced transfers", "median_market_price": "Eligible market sales"
    })
    x_encoding = alt.X(f"{x}:O", title="Sale year")
    return alt.Chart(long).mark_line(point=True, strokeWidth=2.5).encode(
        x=x_encoding,
        y=alt.Y("Median price:Q", title="Median recorded price ($)", scale=alt.Scale(zero=True), axis=alt.Axis(format="$~s", tickCount=6)),
        color=alt.Color("Series:N", scale=alt.Scale(domain=list(COLORS), range=list(COLORS.values())), legend=alt.Legend(title=None, orient="top")),
        strokeDash=alt.StrokeDash("Series:N", legend=None),
        tooltip=[alt.Tooltip(f"{x}:O", title="Sale year"), "Series:N", alt.Tooltip("Median price:Q", format="$,.0f"),
                 alt.Tooltip("eligible_market_sales:Q", title="Eligible sales", format=","),
                 alt.Tooltip("recorded_transfers:Q", title="All transfers", format=",")],
    ).properties(title=title, height=height)


st.caption("ALLEGHENY COUNTY  /  PROPERTY SALE TRANSACTIONS")
st.title("What counts as a sale?")
st.markdown("Recorded property transfers tell a different story from sales classified as representative of market value.")

try:
    publication = current_generation(ROOT / "data")
    is_submission_snapshot = False
except FileNotFoundError:
    publication = ROOT / "results"
    is_submission_snapshot = True

try:
    metrics, coverage, report = load_publication(str(publication))
except (FileNotFoundError, ValueError, KeyError) as error:
    st.error(f"No valid analytical output is available: {error}")
    st.code("python -m sales_pipeline")
    st.stop()

fetched = datetime.fromisoformat(report["snapshot_fetched_at"])
st.caption(
    f"Snapshot retrieved {fetched:%b %d, %Y} · Sale dates through {report['totals']['last_sale_date']} · "
    f"{report['totals']['municipalities']} municipalities · "
    + ("Checked-in submission snapshot" if is_submission_snapshot else "Validated local pipeline output")
)

market_tab, coverage_tab, definitions_tab = st.tabs(["Market comparison", "Source coverage", "Definitions & checks"])

with market_tab:
    years = sorted(metrics.sale_year.unique().tolist())
    # Prefer the last completed calendar year; never silently compare a partial year.
    completed = [year for year in years if year < fetched.year]
    default_year = max(completed) if completed else max(years)
    controls = st.columns([1, 2, 1])
    selected_year = controls[0].selectbox("Sale year", years, index=years.index(default_year))
    year_data = metrics[metrics.sale_year == selected_year].copy()
    municipalities = sorted(year_data.municipality.unique().tolist())
    selected_municipality = controls[1].selectbox(
        "Municipality", municipalities,
        index=municipalities.index("Pittsburgh") if "Pittsburgh" in municipalities else 0,
    )
    threshold = controls[2].selectbox("Minimum eligible sales", [10, 30, 50, 100], index=1,
                                       help="A display rule for comparisons, not a confidence interval or a test of representativeness.")
    if selected_year >= fetched.year:
        st.warning(f"{selected_year} is a partial-year snapshot. Counts are not comparable with full calendar years; recent sales may also arrive late.")
    selected = year_data[year_data.municipality == selected_municipality].iloc[0]
    stats = st.columns(3)
    stats[0].metric("All priced transfers · median", dollars(selected.median_recorded_price),
                    help="Naive benchmark: all resolved transfer records with a price, including zero-dollar and non-market transfers.", border=True)
    stats[1].metric("Eligible market sales · median", dollars(selected.median_market_price),
                    help="SALECODE 0 (VALID SALE), positive price, resolved transfer identity. This is a selected subset of property transfers.", border=True)
    stats[2].metric("Eligible share of recorded transfers", f"{selected.eligible_share:.1%}",
                    help=f"{int(selected.eligible_market_sales):,} eligible sales / {int(selected.recorded_transfers):,} reconciled transfer identities.", border=True)
    st.caption(f"{selected_municipality}, {selected_year}: {int(selected.recorded_transfers):,} recorded transfers; "
               f"{int(selected.transfers_with_price):,} priced transfers; {int(selected.eligible_market_sales):,} eligible market sales.")
    if selected.eligible_market_sales < threshold:
        st.warning(f"Only {int(selected.eligible_market_sales)} eligible sales in this selection; below the {threshold}-sale display threshold. Interpret its median cautiously.")

    st.subheader("Where does the comparison change most?")
    st.caption(f"Ten largest percentage differences in {selected_year}, among municipalities with at least {threshold} eligible sales and a positive all-transfer median.")
    ranked = year_data[
        (year_data.eligible_market_sales >= threshold) & (year_data.median_recorded_price > 0)
        & year_data.median_market_price.notna()
    ].sort_values("median_difference_pct", ascending=False).head(10)
    if ranked.empty:
        st.info("No municipalities meet the current comparison threshold.")
    else:
        long = ranked.melt(
            id_vars=["municipality", "eligible_market_sales", "recorded_transfers", "median_difference_pct"],
            value_vars=["median_recorded_price", "median_market_price"],
            var_name="series", value_name="Median price",
        )
        long["Series"] = long.series.map({"median_recorded_price": "All priced transfers", "median_market_price": "Eligible market sales"})
        chart = alt.Chart(long).mark_point(filled=True, size=95).encode(
            y=alt.Y("municipality:N", sort=ranked.municipality.tolist(), title=None),
            x=alt.X("Median price:Q", title="Median recorded price ($)", axis=alt.Axis(format="$~s", tickCount=6), scale=alt.Scale(zero=True)),
            color=alt.Color("Series:N", scale=alt.Scale(domain=list(COLORS), range=list(COLORS.values())), legend=alt.Legend(title=None, orient="top")),
            shape=alt.Shape("Series:N", scale=alt.Scale(domain=list(COLORS), range=["square", "circle"]), legend=None),
            tooltip=["municipality:N", "Series:N", alt.Tooltip("Median price:Q", format="$,.0f"),
                     alt.Tooltip("median_difference_pct:Q", title="Median difference", format=".1%"),
                     alt.Tooltip("eligible_market_sales:Q", title="Eligible sales", format=","),
                     alt.Tooltip("recorded_transfers:Q", title="All transfers", format=",")],
        ).properties(height=340)
        st.altair_chart(chart, width="stretch", alt="Paired points compare all-transfer and eligible-sale median prices for the ten municipalities with the largest percentage difference. Exact values are in the downloadable table.")

    st.subheader(f"{selected_municipality} over time")
    history = metrics[metrics.municipality == selected_municipality].copy()
    history = history[history.sale_year < fetched.year]
    # Do not join a trend through a low-sample market estimate.
    history.loc[history.eligible_market_sales < threshold, "median_market_price"] = float("nan")
    if not history.empty:
        st.altair_chart(price_chart(history, "sale_year", "Completed calendar years"), width="stretch",
                        alt="Yearly median prices for the selected municipality, comparing all priced transfers with eligible market sales. Low-sample eligible medians are omitted.")
    st.caption("Differences reflect which transfers enter each group. These are nominal property prices, not a same-property appreciation index, home-only prices, or a causal estimate.")

    with st.expander("Explore the exact values", expanded=False):
        table = year_data[["municipality", "recorded_transfers", "eligible_market_sales", "eligible_share", "median_recorded_price", "median_market_price", "median_difference_pct", "love_affection_transfers", "multi_parcel_transfers", "unresolved_conflicts"]]
        st.dataframe(table.sort_values("municipality"), hide_index=True, column_config={
            "eligible_share": st.column_config.NumberColumn(format="percent"),
            "median_difference_pct": st.column_config.NumberColumn(format="percent"),
            "median_recorded_price": st.column_config.NumberColumn(format="dollar"),
            "median_market_price": st.column_config.NumberColumn(format="dollar"),
        })
        st.download_button("Download this year's municipal metrics", year_data.to_csv(index=False), f"municipality_metrics_{selected_year}.csv", "text/csv")

with coverage_tab:
    st.subheader("One dataset. Multiple files. Different coverage.")
    additional = int(coverage.annual_only.sum())
    total = int(coverage.reconciled_transfers.sum())
    st.markdown(f"The annual files contribute **{additional:,} transfer identities** absent from the consolidated file in this snapshot. Reconciliation yields **{total:,} identities** across both sources.")
    counts = st.columns(3)
    counts[0].metric("In both source families", f"{int(coverage.in_both.sum()):,}")
    counts[1].metric("Annual only", f"{additional:,}")
    counts[2].metric("Consolidated only", f"{int(coverage.consolidated_only.sum()):,}")
    coverage_long = coverage.melt(id_vars=["sale_year"], value_vars=["in_both", "annual_only", "consolidated_only"], var_name="Coverage", value_name="Transfers")
    coverage_long["Coverage"] = coverage_long.Coverage.map({"in_both": "Both", "annual_only": "Annual only", "consolidated_only": "Consolidated only"})
    chart = alt.Chart(coverage_long).mark_bar().encode(
        x=alt.X("sale_year:O", title="Sale year"),
        y=alt.Y("Transfers:Q", title="Reconciled parcel transfers"),
        color=alt.Color("Coverage:N", scale=alt.Scale(domain=["Both", "Annual only", "Consolidated only"], range=["#137D8A", "#A35B24", "#78869B"]), legend=alt.Legend(orient="top", title=None)),
        tooltip=[alt.Tooltip("sale_year:O", title="Sale year"), "Coverage:N", alt.Tooltip("Transfers:Q", format=",")],
    ).properties(height=330)
    st.altair_chart(chart, width="stretch", alt="Stacked annual counts distinguish identities found in both source families, annual files only, and the consolidated file only.")
    st.dataframe(coverage, hide_index=True)
    st.caption("Coverage means presence in the downloaded resources, not proof of every real-world sale. A record's absence does not establish why it is absent. The latest observed year is partial.")

with definitions_tab:
    st.subheader("A transparent definition of an eligible sale")
    st.markdown("""
    A transfer enters the market comparison when its **sale code is `0` (`VALID SALE`)**, its price is **positive**, and its identity has **no unresolved conflict**.

    This deliberately narrow definition excludes multi-parcel, family, corrective, unreviewed and preferential-assessment categories. Exclusion does not mean a transfer is erroneous or that its price is meaningless for every purpose.

    **Grain:** one candidate parcel-transfer identity: parcel ID + sale date + deed book + deed page + instrument type. A parcel can transfer repeatedly; a deed can cover several parcels. These counts are not counts of unique deeds.

    **Reconciliation:** prefer the consolidated record for an identity it contains; otherwise use the annual record when uncontested. Retain every source version. Unresolved conflicts count as recorded identities, but their disputed price and sale classification are withheld.

    **Geography:** ward-coded records for Pittsburgh, Clairton, Duquesne and McKeesport are rolled up to their cities. Postal city is not used as municipality.
    """)
    st.caption(f"This snapshot has {report['totals']['unresolved_conflicts']:,} unresolved identities and {report['totals']['incomplete_deed_keys']:,} identities with incomplete deed references. "
               f"It also contains {report['totals']['recording_before_sale']:,} resolved records with recording dates before sale dates; these are retained and flagged in the report.")
    st.subheader("Publication checks")
    st.dataframe(pd.DataFrame(report["checks"]), hide_index=True)
    st.caption("Any nonzero violation blocks a new publication. Raw bytes and all competing source records remain available for inspection locally.")
    st.download_button("Download the full analytical table", (publication / "municipality_year.csv").read_bytes(), "municipality_year.csv", "text/csv")
    st.markdown("Source: [WPRDC Property Sale Transactions](https://data.wprdc.org/dataset/real-estate-sales). Code and analysis assisted by OpenAI Codex; see the repository's AI disclosure.")
