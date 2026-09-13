"""Assembly of the country-month panel and the cost-of-living metric chain."""

from __future__ import annotations

import pandas as pd

from .countries import REDENOMINATED, SHARED_CURRENCIES

PPP_BASE_YEAR = 2020  # PPP factors are quoted for this year, so CPI is rebased to it
US_CODE = "USA"


def _graft_shared_currencies(exchange_rates: pd.DataFrame) -> pd.DataFrame:
    """Copy a currency issuer's rate onto countries that use it but lack their own series."""
    borrowed = []
    for issuer, borrowers in SHARED_CURRENCIES.items():
        issuer_rates = exchange_rates.loc[exchange_rates.country_code == issuer, ["date", "exr"]]
        for code in borrowers:
            borrowed.append(issuer_rates.assign(country_code=code))
    return pd.concat(borrowed, ignore_index=True)


def _drop_post_redenomination(panel: pd.DataFrame) -> pd.DataFrame:
    """Drop months where the PPP factor's currency no longer matches the exchange rate."""
    stale = pd.Series(False, index=panel.index)
    for code, switch_date in REDENOMINATED.items():
        stale |= (panel.country_code == code) & (panel.date >= pd.Timestamp(switch_date))
    return panel.loc[~stale]


def build_panel(
    cpi: pd.DataFrame,
    exchange_rates: pd.DataFrame,
    ppp: pd.DataFrame,
    advisories: pd.DataFrame,
) -> pd.DataFrame:
    """Join the four sources into one country-month panel with derived cost metrics.

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
    panel = _drop_post_redenomination(panel)
    panel = panel.merge(ppp, on="country_code", how="inner")
    panel = panel.merge(
        advisories[["country_code", "advisory_level"]].dropna(subset=["country_code"]),
        on="country_code",
        how="inner",
    )
    panel = panel.drop_duplicates(subset=["country_code", "date"])

    return add_cost_metrics(panel)


def add_cost_metrics(panel: pd.DataFrame, base_year: int = PPP_BASE_YEAR) -> pd.DataFrame:
    """Add the rebased CPI and the three successive cost-in-dollars measures."""
    panel = panel.sort_values(["country_code", "date"]).reset_index(drop=True)

    # Some series (e.g. Australia) start after the base year and cannot be rebased.
    base_cpi = panel.loc[panel.date.dt.year == base_year].groupby("country_code").cpi.mean()
    panel = panel.loc[panel.country_code.isin(base_cpi.index)]
    panel["cpi_rebased"] = panel.cpi / panel.country_code.map(base_cpi) * 100

    # Dollars needed for $1 of base-year US goods; moves only with the exchange rate.
    panel["ppp_dollars"] = panel.ppp / panel.exr

    # Same, now also moving with local inflation; denominated in base-year dollars.
    panel["real_dollars"] = panel.cpi_rebased * panel.ppp_dollars

    # Deflating by US CPI restates it in today's dollars: the headline metric.
    us_cpi = (
        panel.loc[panel.country_code == US_CODE, ["date", "cpi_rebased"]]
        .drop_duplicates("date")
        .rename(columns={"cpi_rebased": "us_cpi"})
        .sort_values("date")
    )
    # Countries report on different lags, so carry the last US reading forward rather
    # than dropping a country for a month the US has not published yet.
    panel = pd.merge_asof(panel.sort_values("date"), us_cpi, on="date", direction="backward")
    panel["current_dollars"] = panel.real_dollars / panel.us_cpi

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
