"""Assembly of the country-month panel and the cost-of-living metric chain."""

from __future__ import annotations

import pandas as pd

from .countries import SHARED_CURRENCIES

US_CODE = "USA"

# The World Bank quotes the index as US = 100; the metrics below are per-dollar ratios.
PLI_SCALE = 100.0


# A redenomination makes the local unit stronger per USD without moving prices, so only a
# *fall* in the rate this large, unmatched by CPI, is a unit change. The five euro
# accessions in the panel span 3.2x (Lithuania) to 340x (Greece); the largest such fall
# that is a genuine market move is well under 2x, so this cleanly separates the two.
# Devaluations move the rate the other way and are never rescaled, whatever their size.
REDENOMINATION_JUMP = 2.5


def _rescale_across_redenominations(panel: pd.DataFrame) -> pd.DataFrame:
    """Restate each country's exchange rate in its most recent currency unit.

    The IMF series splices a redenominated currency onto the old one without rescaling, so
    at euro accession (Greece 2001, Slovenia 2007, Estonia 2011, Lithuania 2015, Croatia
    2023) the rate drops by the conversion factor. Dividing the pre-break months by the
    cumulative factor puts the whole history in today's unit, so it stays usable instead
    of having to be discarded.
    """
    panel = panel.sort_values(["country_code", "date"])
    rate = panel.groupby("country_code").exr
    jump = panel.exr / rate.shift()
    cpi_jump = (panel.cpi / panel.groupby("country_code").cpi.shift()).fillna(1.0)

    # Only a jump the price index does not corroborate is a change of unit.
    is_break = (jump < 1 / REDENOMINATION_JUMP) & (cpi_jump.between(0.5, 2.0))
    factor = jump.where(is_break, 1.0).fillna(1.0)

    # A month is converted to the newest unit by the product of every break at or after
    # the next month, so a reversed cumulative product excluding the row itself.
    reversed_codes = panel.country_code.iloc[::-1]
    to_current = (
        factor.iloc[::-1]
        .groupby(reversed_codes)
        .shift(1)
        .fillna(1.0)
        .groupby(reversed_codes)
        .cumprod()
        .iloc[::-1]
    )

    panel = panel.copy()
    panel["exr"] = panel.exr * to_current
    return panel


def _graft_shared_currencies(exchange_rates: pd.DataFrame) -> pd.DataFrame:
    """Copy a currency issuer's rate onto countries that use it but lack their own series."""
    borrowed = []
    for issuer, borrowers in SHARED_CURRENCIES.items():
        issuer_rates = exchange_rates.loc[exchange_rates.country_code == issuer, ["date", "exr"]]
        for code in borrowers:
            borrowed.append(issuer_rates.assign(country_code=code))
    return pd.concat(borrowed, ignore_index=True)


def build_panel(
    cpi: pd.DataFrame,
    exchange_rates: pd.DataFrame,
    price_level: pd.DataFrame,
    advisories: pd.DataFrame,
) -> pd.DataFrame:
    """Join the sources into one country-month panel with derived cost metrics.

    All inputs are keyed on ISO-3 `country_code`. Joins are inner, so a country missing
    from any source drops out.
    """
    cpi = cpi.rename(columns={"value": "cpi"})
    exchange_rates = exchange_rates.rename(columns={"value": "exr"})

    panel = cpi.merge(exchange_rates, on=["date", "country_code"], how="outer")
    borrowed = _graft_shared_currencies(exchange_rates).rename(columns={"exr": "exr_shared"})
    panel = panel.merge(borrowed, on=["date", "country_code"], how="left")
    panel["exr"] = panel.exr.fillna(panel.exr_shared)
    panel = panel.drop(columns="exr_shared")

    panel = panel.loc[panel.exr.notnull() & panel.cpi.notnull()]
    names = price_level[["country_code", "country_name"]].drop_duplicates("country_code")
    panel = panel.merge(names, on="country_code", how="inner")
    panel = panel.merge(
        advisories[["country_code", "advisory_level"]].dropna(subset=["country_code"]),
        on="country_code",
        how="inner",
    )
    panel = panel.drop_duplicates(subset=["country_code", "date"])

    return add_cost_metrics(panel, price_level)


def _anchor_year(panel: pd.DataFrame, price_level: pd.DataFrame) -> int:
    """Latest year the index and the monthly data both cover for most countries.

    The index is annual and lags; anchoring on its last year keeps the extrapolation as
    short as possible, but that year must also be fully present in the monthly series.
    """
    monthly_years = panel.groupby(panel.date.dt.year).date.nunique()
    complete = set(monthly_years.loc[monthly_years >= 12].index)
    shared = complete & set(price_level.year.unique())
    if not shared:
        raise ValueError("no year is covered by both the price level index and the monthly data")
    return max(shared)


def add_cost_metrics(
    panel: pd.DataFrame, price_level: pd.DataFrame, anchor_year: int | None = None
) -> pd.DataFrame:
    """Anchor each country on its published price level, then nowcast to each month.

    The World Bank index is annual and published with a lag. Each country is pinned to its
    anchor-year value and carried forward by how far its own prices, converted at the
    current exchange rate, have moved against US prices.
    """
    panel = panel.sort_values(["country_code", "date"]).reset_index(drop=True)
    if anchor_year is None:
        anchor_year = _anchor_year(panel, price_level)

    panel = _rescale_across_redenominations(panel)

    # Real dollar prices up to an unknown country-specific constant, which the anchor sets.
    panel["local_in_usd"] = panel.cpi / panel.exr

    us = (
        panel.loc[panel.country_code == US_CODE, ["date", "cpi"]]
        .drop_duplicates("date")
        .rename(columns={"cpi": "us_cpi"})
        .sort_values("date")
    )
    # Countries report on different lags, so carry the last US reading forward rather
    # than dropping a country for a month the US has not published yet.
    panel = pd.merge_asof(panel.sort_values("date"), us, on="date", direction="backward")
    panel["relative_prices"] = panel.local_in_usd / panel.us_cpi

    anchor_index = (
        price_level.loc[price_level.year == anchor_year].set_index("country_code").price_level_index
    )
    anchor_relative = (
        panel.loc[panel.date.dt.year == anchor_year].groupby("country_code").relative_prices.mean()
    )

    # A country needs both an anchor level and a full anchor year of monthly data.
    usable = anchor_index.index.intersection(anchor_relative.index)
    panel = panel.loc[panel.country_code.isin(usable)]

    # Scale factor converting this country's relative prices into index units.
    calibration = (anchor_index[usable] / anchor_relative[usable]).rename("calibration")
    panel = panel.merge(calibration, left_on="country_code", right_index=True, how="inner")

    panel["price_level_nowcast"] = panel.relative_prices * panel.calibration
    # The headline metric: dollars needed abroad for $1 of US goods, so the US is 1.0.
    panel["current_dollars"] = panel.price_level_nowcast / PLI_SCALE

    return panel.sort_values(["country_code", "date"]).reset_index(drop=True)


def rank_latest(
    panel: pd.DataFrame,
    metric: str = "current_dollars",
    max_advisory: int = 2,
    max_staleness_months: int = 6,
) -> pd.DataFrame:
    """Countries ranked cheapest to most expensive, each at its own latest month.

    Countries report CPI on different lags, so a single shared date would cover only a
    fraction of them; `max_staleness_months` bounds how far behind a reading may be.
    """
    eligible = panel.loc[panel.advisory_level <= max_advisory].dropna(subset=[metric])
    latest = eligible.loc[eligible.groupby("country_code").date.idxmax()]

    cutoff = panel.date.max() - pd.DateOffset(months=max_staleness_months)
    latest = latest.loc[latest.date >= cutoff]
    return latest.sort_values(metric)[
        ["country_name", "date", "advisory_level", metric]
    ].reset_index(drop=True)


def rank_change(
    panel: pd.DataFrame,
    start: str,
    end: str,
    metric: str = "current_dollars",
    max_advisory: int = 2,
) -> pd.DataFrame:
    """Percent change in `metric` between two dates, most-increased first."""
    eligible = panel.loc[panel.advisory_level <= max_advisory]
    endpoints = eligible.loc[eligible.date.isin(pd.to_datetime([start, end]))]

    wide = endpoints.pivot_table(
        index=["country_name", "advisory_level"], columns="date", values=metric
    ).dropna()
    wide.columns = ["start", "end"]
    wide["pct_change"] = wide.end / wide.start - 1
    return wide.sort_values("pct_change", ascending=False).reset_index()


def compare_to_official(
    panel: pd.DataFrame,
    price_level: pd.DataFrame,
    metric: str = "current_dollars",
    since: int | None = None,
) -> pd.DataFrame:
    """The nowcast against the published index, per country-year. Drives the agreement test.

    Annual means of the nowcast are compared with the index for the same year; `ratio` is
    1.0 where they agree, and the anchor year agrees by construction. Agreement decays the
    further a year sits from the anchor -- 97% of country-years within 10% for 2023 on,
    81% from 2015 -- so `since` restricts the comparison to the recent window that the
    headline ranking actually draws on.
    """
    annual = (
        panel.assign(year=panel.date.dt.year)
        .groupby(["country_code", "country_name", "year"])[metric]
        .mean()
        .mul(PLI_SCALE)
        .rename("nowcast")
        .reset_index()
    )
    merged = annual.merge(
        price_level.drop(columns="country_name", errors="ignore"),
        on=["country_code", "year"],
        how="inner",
    )
    if since is not None:
        merged = merged.loc[merged.year >= since]
    merged["ratio"] = merged.nowcast / merged.price_level_index
    return merged.sort_values(["country_code", "year"]).reset_index(drop=True)
