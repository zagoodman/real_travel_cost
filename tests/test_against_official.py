"""Agreement between the nowcast and the published World Bank index. Hits the live API.

Deselected by default; run with `uv run pytest -m network`. This is the check that catches
a unit mismatch: a stale or misscaled currency shows up as a country whose nowcast diverges
from the official series by orders of magnitude, which no offline fixture would reveal.
"""

import pandas as pd
import pytest

from real_travel_cost import compare_to_official, fetch_price_level_index, load_panel
from real_travel_cost.metrics import PLI_SCALE

# Agreement decays with distance from the anchor, so the guard covers the recent window the
# headline ranking draws on rather than the full history back to 2000.
SINCE = 2023


@pytest.fixture(scope="module")
def comparison():
    price_level = fetch_price_level_index()
    return compare_to_official(load_panel(), price_level, since=SINCE)


@pytest.mark.network
def test_no_country_diverges_by_an_order_of_magnitude(comparison):
    """A currency unit mismatch shows up here and nowhere else."""
    outliers = comparison.loc[(comparison.ratio > 3) | (comparison.ratio < 1 / 3)]
    assert outliers.empty, f"unit mismatch suspected:\n{outliers}"


@pytest.mark.network
def test_most_country_years_agree_closely(comparison):
    close = comparison.ratio.sub(1).abs().le(0.10).mean()
    assert close >= 0.90, f"only {close:.1%} of country-years within 10%"


@pytest.mark.network
def test_us_is_exactly_the_baseline():
    """The World Bank fixes the US at 100, so the nowcast must put it at exactly 1.0."""
    panel = load_panel()
    assert panel.loc[panel.country_code == "USA", "current_dollars"].eq(1.0).all()


@pytest.mark.network
def test_no_country_is_an_implausible_multiple_of_us_prices():
    """Nowhere is more than ~2.5x US prices; a big outlier means a currency mismatch."""
    panel = load_panel()
    latest = panel.loc[panel.date >= panel.date.max() - pd.DateOffset(months=6)]
    assert latest.current_dollars.max() < 2.5


@pytest.mark.network
def test_published_index_keeps_the_us_at_one_hundred():
    """The anchor's own baseline; if this breaks, the indicator changed meaning."""
    price_level = fetch_price_level_index()
    us = price_level.loc[price_level.country_code == "USA", "price_level_index"]
    assert us.eq(PLI_SCALE).all()
