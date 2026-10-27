"""A local, read-only explanation of source coverage and transfer composition."""

import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from sales_pipeline.storage import ROOT, current_generation, data_directory, verify_bundle

TEAL = "#137D8A"
AMBER = "#A35B24"
GRAY = "#7A8797"
st.set_page_config(
    page_title="Which transfers count? · Allegheny County", page_icon="📊", layout="wide"
)


def money(value):
    return "Unavailable" if pd.isna(value) else f"${value:,.0f}"


def markdown_money(value):
    # Two dollar amounts on one line otherwise become a LaTeX expression.
    return money(value).replace("$", "\\$")


def choose_example(city, year):
    st.session_state["municipality"] = city
    st.session_state["sale_year"] = year


def load_data():
    # The bundle is small: verify every presented CSV on every rerun. No stale cache.
    try:
        directory = current_generation(data_directory())
        label = "Validated local publication"
    except FileNotFoundError:
        directory = ROOT / "results"
        label = "Checked-in submission snapshot"
    report = verify_bundle(directory)
    return directory, report, label


try:
    publication, report, source_label = load_data()
    metrics = pd.read_csv(publication / "municipality_year.csv")
    coverage = pd.read_csv(publication / "source_reconciliation.csv")
    deeds = pd.read_csv(
        publication / "repeated_deed_examples.csv", dtype={"deed_book": str, "deed_page": str}
    )
except (OSError, ValueError, KeyError) as error:
    st.title("The analytical output needs attention")
    st.error(str(error))
    st.code("python -m sales_pipeline\npython -m streamlit run dashboard.py")
    st.stop()

st.caption("ALLEGHENY COUNTY · WPRDC PROPERTY SALE TRANSACTIONS")
st.title("Which transfers count?")
st.markdown("Compare all priced property transfers with publisher-classified standard-valid sales.")
st.caption(
    f"{source_label} · Retrieved {report['snapshot_fetched_at'][:10]} · Sale dates through {report['totals']['last_sale_date']}"
)
additional = int(coverage.annual_only.sum())
st.markdown(
    f"**Source coverage:** annual files add **{additional:,}** identities absent from the consolidated CSV. Details in **Check source coverage**."
)

finding, sources, methods = st.tabs(
    ["Understand the finding", "Check source coverage", "Methods & checks"]
)

with finding:
    summary = st.container()
    years = sorted(metrics.sale_year.unique().tolist())
    cities = sorted(metrics.municipality.unique().tolist())
    default_year = max([y for y in years if y < int(report["snapshot_fetched_at"][:4])] or years)
    st.session_state.setdefault("sale_year", default_year)
    st.session_state.setdefault(
        "municipality", "Pittsburgh" if "Pittsburgh" in cities else cities[0]
    )
    examples = st.columns(2)
    examples[0].button(
        "Pittsburgh · 2025: a higher standard-valid median",
        on_click=choose_example,
        args=("Pittsburgh", 2025),
        disabled=2025 not in years or "Pittsburgh" not in cities,
    )
    examples[1].button(
        "Clairton · 2020: the opposite direction",
        on_click=choose_example,
        args=("Clairton", 2020),
        disabled=2020 not in years or "Clairton" not in cities,
    )
    with st.expander("Choose another municipality or year"):
        selectors = st.columns(2)
        year = selectors[0].selectbox("Sale year", years, key="sale_year")
        city = selectors[1].selectbox("Municipality", cities, key="municipality")
    selection = metrics[(metrics.sale_year == year) & (metrics.municipality == city)]
    if selection.empty:
        st.warning("No recorded transfers for this municipality/year. Choose another selection.")
    else:
        row = selection.iloc[0]
        with summary:
            st.subheader(f"{city}, {year}")
            st.markdown(
                f"**{markdown_money(row.median_all_transfer_price)}** across all priced transfers → **{markdown_money(row.median_standard_valid_price)}** among standard-valid sales."
            )
            st.caption(
                "Standard-valid = publisher code 0 / VALID SALE, positive price and no flagged identity uncertainty. This subset is included in all priced transfers."
            )
        if row.is_partial_year:
            st.warning(
                f"{year} is partial. Do not compare its transfer count directly with a completed calendar year."
            )
        if row.standard_valid_sales < 30:
            st.warning(
                f"Only {int(row.standard_valid_sales):,} standard-valid sales. This median is based on a small selected subset."
            )
        panels = st.columns([1, 1.15])
        price_data = pd.DataFrame(
            {
                "Group": [
                    f"All priced transfers · n={int(row.priced_transfers):,}",
                    f"Standard-valid sales · n={int(row.standard_valid_sales):,}",
                ],
                "Median": [row.median_all_transfer_price, row.median_standard_valid_price],
                "Color": [AMBER, TEAL],
            }
        ).dropna(subset=["Median"])
        with panels[0]:
            st.markdown("**Two medians, with their sample sizes**")
            bars = (
                alt.Chart(price_data)
                .mark_bar(size=36)
                .encode(
                    y=alt.Y(
                        "Group:N",
                        sort=price_data.Group.tolist(),
                        title=None,
                        axis=alt.Axis(labelLimit=280),
                    ),
                    x=alt.X(
                        "Median:Q",
                        title="Nominal dollars",
                        axis=alt.Axis(format="$~s", tickCount=4),
                        scale=alt.Scale(zero=True),
                    ),
                    color=alt.Color("Color:N", scale=None, legend=None),
                    tooltip=["Group:N", alt.Tooltip("Median:Q", format="$,.2f")],
                )
            )
            labels = bars.mark_text(align="left", dx=5, color="#182C40").encode(
                text=alt.Text("Median:Q", format="$,.0f")
            )
            st.altair_chart(
                (bars + labels).properties(height=210).configure_view(strokeWidth=0),
                width="stretch",
                alt=f"{city} {year}: all priced transfers median {money(row.median_all_transfer_price)}, standard-valid median {money(row.median_standard_valid_price)}. Exact counts and values are shown in text.",
            )
        composition = pd.DataFrame(
            {
                "Transfer type": [
                    "Standard-valid sales",
                    "Family transfers",
                    "Multi-parcel transfers",
                    "Other transfers",
                    "Missing price",
                    "Identity needs review",
                ],
                "Records": [
                    row.standard_valid_sales,
                    row.family_transfers,
                    row.multi_parcel_transfers,
                    row.other_transfers,
                    row.missing_price_transfers,
                    row.identity_review_transfers,
                ],
            }
        )
        composition["Share"] = composition.Records / row.recorded_transfers
        with panels[1]:
            st.markdown(f"**What the {int(row.recorded_transfers):,} recorded identities contain**")
            chart = (
                alt.Chart(composition)
                .mark_bar(size=19, color=TEAL)
                .encode(
                    y=alt.Y(
                        "Transfer type:N",
                        sort=composition["Transfer type"].tolist(),
                        title=None,
                        axis=alt.Axis(labelLimit=170),
                    ),
                    x=alt.X(
                        "Records:Q",
                        title="Candidate parcel-transfer identities",
                        axis=alt.Axis(format="~s", tickCount=4),
                    ),
                    tooltip=[
                        "Transfer type:N",
                        alt.Tooltip("Records:Q", format=","),
                        alt.Tooltip("Share:Q", format=".1%"),
                    ],
                )
            )
            labels = chart.mark_text(align="left", dx=4, color="#182C40").encode(
                text=alt.Text("Records:Q", format=",")
            )
            st.altair_chart(
                (chart + labels).properties(height=210).configure_view(strokeWidth=0),
                width="stretch",
                alt="Six mutually exclusive transfer categories add up to the recorded identity count. The exact category counts are available below.",
            )
        family_text = f"Family transfers: **{int(row.family_transfers):,}** records, median **{markdown_money(row.median_family_price)}**."
        multi_text = f"Multi-parcel transfers: **{int(row.multi_parcel_transfers):,}** records; their price may describe an entire group of parcels."
        st.markdown(family_text + " " + multi_text)
        example = deeds[(deeds.municipality == city) & (deeds.sale_year == year)]
        if not example.empty:
            deed = example.iloc[0]
            st.caption(
                f"Concrete example: {int(deed.distinct_parcels):,} distinct parcels share deed book {deed.deed_book}/page {deed.deed_page} and repeat a {money(deed.price)} price. This is an observed pattern; do not sum that price across those parcel rows."
            )
        st.caption(
            f"{int(row.standard_valid_sales):,} standard-valid sales / {int(row.recorded_transfers):,} recorded identities = {row.standard_valid_share:.1%}. "
            f"{int(row.identity_review_transfers):,} identities are withheld from price analysis; {int(row.missing_price_transfers):,} otherwise usable identities lack a price."
        )
        st.caption(
            "These groups differ in transaction composition. Their median difference is not price appreciation, a causal effect or an estimate confined to homes."
        )
        with st.expander("Exact values for this selection"):
            st.dataframe(
                composition,
                hide_index=True,
                column_config={"Share": st.column_config.NumberColumn(format="percent")},
            )
            st.dataframe(selection, hide_index=True)

    with st.expander(f"Compare municipalities in {year}"):
        st.caption(
            "This section compares all municipalities in the selected year; the municipality selector above controls the example and its history."
        )
        controls = st.columns(2)
        minimum = controls[0].selectbox(
            "Minimum standard-valid sales for comparison", [10, 30, 50, 100], index=1
        )
        direction = controls[1].selectbox(
            "Comparison direction",
            [
                "Largest changes in either direction",
                "Higher standard-valid medians",
                "Lower standard-valid medians",
            ],
        )
        comparison = metrics[
            (metrics.sale_year == year)
            & (metrics.standard_valid_sales >= minimum)
            & metrics.median_gap_pct.notna()
        ].copy()
        if direction == "Higher standard-valid medians":
            comparison = comparison[comparison.median_gap_pct > 0].sort_values(
                "median_gap_pct", ascending=False
            )
        elif direction == "Lower standard-valid medians":
            comparison = comparison[comparison.median_gap_pct < 0].sort_values("median_gap_pct")
        else:
            comparison = comparison.assign(magnitude=comparison.median_gap_pct.abs()).sort_values(
                "magnitude", ascending=False
            )
        if comparison.empty:
            st.info("No municipalities meet this direction and sample-size filter.")
        else:
            top = comparison.head(10)
            chart = (
                alt.Chart(top)
                .mark_bar()
                .encode(
                    y=alt.Y("municipality:N", sort=top.municipality.tolist(), title=None),
                    x=alt.X(
                        "median_gap_pct:Q",
                        title="Standard-valid median / all-transfer median − 1",
                        axis=alt.Axis(format=".0%"),
                    ),
                    color=alt.condition(
                        alt.datum.median_gap_pct >= 0, alt.value(TEAL), alt.value(AMBER)
                    ),
                    tooltip=[
                        "municipality:N",
                        alt.Tooltip("median_gap_pct:Q", title="Difference", format="+.1%"),
                        alt.Tooltip(
                            "standard_valid_sales:Q", title="Standard-valid sales", format=","
                        ),
                    ],
                )
                .properties(height=310)
            )
            st.altair_chart(
                chart,
                width="stretch",
                alt="Signed percentage differences are ranked by the selected direction. Exact prices and differences are in the accompanying table.",
            )
            st.dataframe(
                comparison[
                    [
                        "municipality",
                        "standard_valid_sales",
                        "median_all_transfer_price",
                        "median_standard_valid_price",
                        "median_gap_pct",
                    ]
                ],
                hide_index=True,
                column_config={
                    "median_gap_pct": st.column_config.NumberColumn(
                        "Median difference", format="percent"
                    ),
                    "median_all_transfer_price": st.column_config.NumberColumn(
                        "All priced transfers", format="dollar"
                    ),
                    "median_standard_valid_price": st.column_config.NumberColumn(
                        "Standard-valid sales", format="dollar"
                    ),
                },
            )
        st.caption(
            "The sample threshold is a display choice, not a confidence interval or a guarantee of representativeness."
        )

    with st.expander(f"History for {city}"):
        include_partial = st.checkbox("Include the partial latest year", value=False)
        history = metrics[metrics.municipality == city].copy()
        if not include_partial:
            history = history[~history.is_partial_year]
        if not history.empty:
            long = history.melt(
                id_vars=["sale_year", "standard_valid_sales"],
                value_vars=["median_all_transfer_price", "median_standard_valid_price"],
                var_name="Series",
                value_name="Median",
            )
            long["Series"] = long.Series.map(
                {
                    "median_all_transfer_price": "All priced transfers",
                    "median_standard_valid_price": "Standard-valid sales",
                }
            )
            chart = (
                alt.Chart(long)
                .mark_line(point=True)
                .encode(
                    x=alt.X("sale_year:O", title="Sale year"),
                    y=alt.Y(
                        "Median:Q",
                        title="Nominal dollars",
                        scale=alt.Scale(zero=True),
                        axis=alt.Axis(format="$~s"),
                    ),
                    color=alt.Color(
                        "Series:N",
                        scale=alt.Scale(
                            domain=["All priced transfers", "Standard-valid sales"],
                            range=[AMBER, TEAL],
                        ),
                        legend=alt.Legend(title=None, orient="top"),
                    ),
                    tooltip=[
                        "sale_year:O",
                        "Series:N",
                        alt.Tooltip("Median:Q", format="$,.0f"),
                        "standard_valid_sales:Q",
                    ],
                )
                .properties(height=230)
            )
            st.altair_chart(
                chart,
                width="stretch",
                alt="Yearly medians for the selected municipality. Sample sizes and standard-valid shares appear in the table below.",
            )
            st.dataframe(
                history[
                    [
                        "sale_year",
                        "recorded_transfers",
                        "standard_valid_sales",
                        "standard_valid_share",
                        "is_partial_year",
                    ]
                ],
                hide_index=True,
                column_config={
                    "standard_valid_share": st.column_config.NumberColumn(format="percent")
                },
            )
        st.caption(
            "Property mix, classification reviews and recording delays can change over time. This is not a same-property price index."
        )

with sources:
    st.subheader("Verify coverage before interpreting the market")
    st.markdown(
        f"**{int(coverage.in_both.sum()):,}** identities occur in both families; **{additional:,}** occur only in annual files; **{int(coverage.consolidated_only.sum()):,}** occur only in the consolidated file."
    )
    coverage["Consolidated coverage"] = (
        coverage.in_both + coverage.consolidated_only
    ) / coverage.reconciled_transfers
    long = coverage.melt(
        id_vars=["sale_year"],
        value_vars=["in_both", "annual_only", "consolidated_only"],
        var_name="Source presence",
        value_name="Identities",
    )
    long["Source presence"] = long["Source presence"].map(
        {"in_both": "Both", "annual_only": "Annual only", "consolidated_only": "Consolidated only"}
    )
    chart = (
        alt.Chart(long)
        .mark_bar()
        .encode(
            x=alt.X("sale_year:O", title="Sale year"),
            y=alt.Y("Identities:Q", title="Candidate transfer identities"),
            color=alt.Color(
                "Source presence:N",
                scale=alt.Scale(
                    domain=["Both", "Annual only", "Consolidated only"], range=[TEAL, AMBER, GRAY]
                ),
                legend=alt.Legend(title=None, orient="top"),
            ),
            tooltip=["sale_year:O", "Source presence:N", alt.Tooltip("Identities:Q", format=",")],
        )
        .properties(height=300)
    )
    st.altair_chart(
        chart,
        width="stretch",
        alt="Yearly coverage shows substantial annual-only records in recent years. Exact counts and coverage percentages appear below.",
    )
    st.dataframe(
        coverage,
        hide_index=True,
        column_config={"Consolidated coverage": st.column_config.NumberColumn(format="percent")},
    )
    st.caption(
        "Latest-year counts are partial. A missing record does not establish whether the cause is publication timing, a correction, or another upstream process."
    )

with methods:
    st.subheader("What is counted—and what stays under review")
    st.markdown("""
    **Unit:** a candidate parcel-transfer identity: parcel + sale date + deed book + deed page + instrument.
    One parcel may transfer repeatedly; one deed may cover several parcels. These are not unique-deed counts.

    **Price analysis:** neither source family wins a dispute. Conflicting analytical values, incomplete deed keys and potential same-deed/different-date corrections are excluded from both medians. Source variants remain inspectable.
    Descriptive-only differences do not discard an agreed price or classification.

    **Geography:** all 175 source code/name pairs appear in a checked reference CSV. Four ward-coded cities roll up to 130 municipality-level units; other municipalities pass through. City rollup identifiers are project-assigned.

    **Definition:** standard-valid is publisher code 0 / VALID SALE with a positive price and usable identity. Other classifications can be legitimate transfers; exclusion is not an assertion of bad data.
    """)
    t = report["totals"]
    st.caption(
        f"{t['conflicting_values']:,} identities have conflicting analytical values; {t['incomplete_deed_keys']:,} have incomplete deed keys; "
        f"{t['potential_date_conflicts']:,} have potential date conflicts. These diagnostics may overlap. "
        f"{t['identity_review_transfers']:,} distinct identities are withheld from price analysis."
    )
    st.dataframe(pd.DataFrame(report["checks"]), hide_index=True)
    st.caption(
        "A failed run preserves the prior publication and writes checks plus bounded examples to data/failures/. This page verifies checksums of every presented audit output on each rerun."
    )
    for filename, label in [
        ("municipality_year.csv", "Download the analytical table"),
        ("review_records.csv", "Download the identity review evidence"),
    ]:
        st.download_button(label, (publication / filename).read_bytes(), filename, "text/csv")
    st.markdown(
        "[WPRDC source](https://data.wprdc.org/dataset/real-estate-sales) · [Code, methods and AI disclosure](https://github.com/raindexllc/allegheny-county-property-sales)"
    )
