"""Metric-chain tests on a hand-built panel with known answers. No network."""

import pandas as pd
import pytest

from real_travel_cost.countries import attach_country_codes, unmatched
from real_travel_cost.metrics import add_cost_metrics, build_panel, rank_change, rank_latest

DATES = pd.to_datetime(["2020-01-01", "2024-01-01"])


def _panel() -> pd.DataFrame:
    """US flat; Foreignia doubles prices as its currency halves, so its cost holds at $0.50."""
    rows = [
        ("USA", "United States", DATES[0], 100.0, 1.0, 1.0, 1),
        ("USA", "United States", DATES[1], 100.0, 1.0, 1.0, 1),
        ("FGN", "Foreignia", DATES[0], 100.0, 20.0, 10.0, 2),
        ("FGN", "Foreignia", DATES[1], 200.0, 40.0, 10.0, 2),
    ]
    return pd.DataFrame(
        rows,
        columns=["country_code", "country_name", "date", "cpi", "exr", "ppp", "advisory_level"],
    )


def test_base_year_cpi_is_rebased_to_100():
    out = add_cost_metrics(_panel())
    assert out.loc[out.date == DATES[0], "cpi_rebased"].eq(100).all()


def test_inflation_offsets_devaluation():
    out = add_cost_metrics(_panel()).set_index(["country_code", "date"])
    assert out.loc[("FGN", DATES[1]), "current_dollars"] == pytest.approx(
        out.loc[("FGN", DATES[0]), "current_dollars"]
    )


def test_us_baseline_is_one_dollar_per_dollar():
    out = add_cost_metrics(_panel())
    assert out.loc[out.country_code == "USA", "current_dollars"].eq(1.0).all()


def test_devaluation_without_inflation_is_cheaper():
    panel = _panel()
    panel.loc[3, "cpi"] = 100.0  # currency still halves, prices now flat
    out = add_cost_metrics(panel).set_index(["country_code", "date"])
    assert out.loc[("FGN", DATES[1]), "current_dollars"] == pytest.approx(
        out.loc[("FGN", DATES[0]), "current_dollars"] / 2
    )


def test_series_without_base_year_is_dropped():
    panel = _panel()
    panel.loc[panel.country_code == "FGN", "date"] = DATES[1]  # no base-year observation
    out = add_cost_metrics(panel)
    assert out.country_code.unique().tolist() == ["USA"]
    assert out.current_dollars.notnull().all()


def test_build_panel_grafts_shared_currency():
    """France has no exchange rate of its own; it must inherit the euro area's."""
    cpi = pd.DataFrame(
        {
            "country_code": ["G163", "FRA", "USA"] * 2,
            "date": list(DATES.repeat(3)),
            "value": [100.0] * 6,
        }
    )
    exr = pd.DataFrame(
        {
            "country_code": ["G163", "USA"] * 2,
            "date": list(DATES.repeat(2)),
            "value": [0.9, 1.0, 0.9, 1.0],
        }
    )
    ppp = pd.DataFrame(
        {
            "country_code": ["FRA", "USA"],
            "country_name": ["France", "United States"],
            "ppp": [0.7, 1.0],
        }
    )
    advisories = pd.DataFrame({"country_code": ["FRA", "USA"], "advisory_level": [2, 1]})

    out = build_panel(cpi, exr, ppp, advisories)
    assert out.loc[out.country_code == "FRA", "exr"].eq(0.9).all()


def test_build_panel_drops_months_after_redenomination():
    """Croatia's PPP is in kuna, so its euro-era months must not be priced."""
    dates = pd.to_datetime(["2020-01-01", "2024-01-01"])
    codes = ["HRV", "USA"]
    cpi = pd.DataFrame(
        {"country_code": codes * 2, "date": list(dates.repeat(2)), "value": [100.0] * 4}
    )
    exr = pd.DataFrame(
        {"country_code": codes * 2, "date": list(dates.repeat(2)), "value": [6.75, 1.0, 0.92, 1.0]}
    )
    ppp = pd.DataFrame(
        {
            "country_code": codes,
            "country_name": ["Croatia", "United States"],
            "ppp": [3.24, 1.0],
        }
    )
    advisories = pd.DataFrame({"country_code": codes, "advisory_level": [1, 1]})

    out = build_panel(cpi, exr, ppp, advisories)
    assert out.loc[out.country_code == "HRV", "date"].max() < pd.Timestamp("2023-01-01")


def test_rank_latest_orders_cheapest_first():
    ranked = rank_latest(add_cost_metrics(_panel()))
    assert ranked.country_name.tolist() == ["Foreignia", "United States"]


def test_rank_latest_excludes_high_advisory():
    panel = _panel()
    panel.loc[panel.country_code == "FGN", "advisory_level"] = 4
    assert rank_latest(add_cost_metrics(panel)).country_name.tolist() == ["United States"]


def test_rank_latest_uses_each_countrys_own_latest_month():
    """A country reporting a month behind still ranks, rather than dropping out."""
    panel = _panel()
    panel.loc[3, "date"] = DATES[1] - pd.DateOffset(months=1)
    ranked = rank_latest(add_cost_metrics(panel))
    assert set(ranked.country_name) == {"Foreignia", "United States"}


def test_rank_latest_excludes_stale_readings():
    panel = _panel()
    panel.loc[3, "date"] = DATES[1] - pd.DateOffset(months=24)
    ranked = rank_latest(add_cost_metrics(panel), max_staleness_months=6)
    assert ranked.country_name.tolist() == ["United States"]


def test_rank_change_reports_percent_change():
    panel = _panel()
    panel.loc[3, "cpi"] = 100.0
    changes = rank_change(add_cost_metrics(panel), "2020-01-01", "2024-01-01")
    assert changes.set_index("country_name").loc["Foreignia", "pct_change"] == pytest.approx(-0.5)


def test_attach_country_codes_maps_names_and_falls_back_to_reference():
    advisories = pd.DataFrame(
        {"country_name": ["Turkiye", "France", "Atlantis"], "advisory_level": [2, 1, 1]}
    )
    reference = pd.DataFrame({"country_name": ["France"], "country_code": ["FRA"]})

    out = attach_country_codes(advisories, reference).set_index("country_name")
    assert out.loc["Turkiye", "country_code"] == "TUR"
    assert out.loc["France", "country_code"] == "FRA"
    assert pd.isna(out.loc["Atlantis", "country_code"])
    assert unmatched(out.reset_index()).tolist() == ["Atlantis"]


def test_devaluation_figure_labels_both_panels():
    """The figure must read from the panel, not from hardcoded headline numbers."""
    from matplotlib import pyplot as plt

    from real_travel_cost.plotting import plot_devaluation_vs_real_cost

    dates = pd.date_range("2015-01-01", periods=24, freq="MS")
    frame = pd.DataFrame(
        {
            "country_code": "TUR",
            "country_name": "Turkiye",
            "date": dates,
            "exr": range(1, 25),  # currency ends 24x weaker
            "current_dollars": 0.5,  # but real cost never moves
        }
    )
    fig = plot_devaluation_vs_real_cost(frame)
    top, bottom = fig.axes

    assert "24x cheaper" in top.get_title()
    assert "+0% since 2015" in "".join(t.get_text() for t in bottom.texts)
    plt.close(fig)
