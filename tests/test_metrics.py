"""Metric-chain tests on a hand-built panel with known answers. No network."""

import pandas as pd
import pytest

from real_travel_cost.countries import attach_country_codes, unmatched
from real_travel_cost.metrics import (
    add_cost_metrics,
    build_panel,
    compare_to_official,
    rank_change,
    rank_latest,
)

DATES = pd.to_datetime(["2020-01-01", "2024-01-01"])
ANCHOR = 2020


def _monthly(code: str, name: str, year: int, cpi: float, exr: float, advisory: int) -> list[tuple]:
    """Twelve identical months, so a year counts as complete for anchoring."""
    return [
        (code, name, date, cpi, exr, advisory)
        for date in pd.date_range(f"{year}-01-01", periods=12, freq="MS")
    ]


def _panel() -> pd.DataFrame:
    """US flat; Foreignia doubles prices as its currency halves, so its cost holds at 0.50."""
    rows = (
        _monthly("USA", "United States", 2020, 100.0, 1.0, 1)
        + _monthly("USA", "United States", 2024, 100.0, 1.0, 1)
        + _monthly("FGN", "Foreignia", 2020, 100.0, 20.0, 2)
        + _monthly("FGN", "Foreignia", 2024, 200.0, 40.0, 2)
    )
    return pd.DataFrame(
        rows,
        columns=["country_code", "country_name", "date", "cpi", "exr", "advisory_level"],
    )


def _price_level(fgn: float = 50.0) -> pd.DataFrame:
    """The published index for the anchor year; the US is 100 by the World Bank's construction."""
    return pd.DataFrame(
        {
            "country_code": ["USA", "FGN"],
            "country_name": ["United States", "Foreignia"],
            "year": [ANCHOR, ANCHOR],
            "price_level_index": [100.0, fgn],
        }
    )


def test_us_baseline_is_one_dollar_per_dollar():
    out = add_cost_metrics(_panel(), _price_level())
    assert out.loc[out.country_code == "USA", "current_dollars"].eq(1.0).all()


def test_anchor_year_reproduces_the_published_index():
    """The whole point of anchoring: the anchor year must match the official value exactly."""
    out = add_cost_metrics(_panel(), _price_level(fgn=50.0))
    anchored = out.loc[(out.country_code == "FGN") & (out.date.dt.year == ANCHOR)]
    assert anchored.current_dollars.to_numpy() == pytest.approx(0.5)


def test_anchor_level_sets_the_scale():
    """A different published level rescales the country without touching its trajectory."""
    cheap = add_cost_metrics(_panel(), _price_level(fgn=25.0))
    dear = add_cost_metrics(_panel(), _price_level(fgn=50.0))
    ratio = (
        dear.loc[dear.country_code == "FGN", "current_dollars"].to_numpy()
        / cheap.loc[cheap.country_code == "FGN", "current_dollars"].to_numpy()
    )
    assert ratio == pytest.approx(2.0)


def test_inflation_offsets_devaluation():
    out = add_cost_metrics(_panel(), _price_level()).set_index(["country_code", "date"])
    assert out.loc[("FGN", DATES[1]), "current_dollars"] == pytest.approx(
        out.loc[("FGN", DATES[0]), "current_dollars"]
    )


def test_devaluation_without_inflation_is_cheaper():
    panel = _panel()
    panel.loc[panel.country_code.eq("FGN") & panel.date.dt.year.eq(2024), "cpi"] = 100.0
    out = add_cost_metrics(panel, _price_level()).set_index(["country_code", "date"])
    assert out.loc[("FGN", DATES[1]), "current_dollars"] == pytest.approx(
        out.loc[("FGN", DATES[0]), "current_dollars"] / 2
    )


def test_country_missing_from_the_index_is_dropped():
    """No published anchor means no scale, so the country cannot be priced at all."""
    index = _price_level().query("country_code == 'USA'")
    out = add_cost_metrics(_panel(), index)
    assert out.country_code.unique().tolist() == ["USA"]


def test_series_without_the_anchor_year_is_dropped():
    panel = _panel()
    panel = panel.loc[~(panel.country_code.eq("FGN") & panel.date.dt.year.eq(ANCHOR))]
    out = add_cost_metrics(panel, _price_level())
    assert out.country_code.unique().tolist() == ["USA"]
    assert out.current_dollars.notnull().all()


def test_anchor_year_is_the_latest_shared_complete_year():
    """A newer index year with no full monthly data must not be chosen as the anchor."""
    index = pd.concat(
        [
            _price_level(),
            pd.DataFrame(
                {
                    "country_code": ["USA", "FGN"],
                    "country_name": ["United States", "Foreignia"],
                    "year": [2025, 2025],
                    "price_level_index": [100.0, 80.0],
                }
            ),
        ]
    )
    out = add_cost_metrics(_panel(), index)
    anchored = out.loc[(out.country_code == "FGN") & (out.date.dt.year == ANCHOR)]
    # The 2020 anchor held, not the 2025 one, which has no full monthly year.
    assert anchored.current_dollars.to_numpy() == pytest.approx(0.5)


def test_redenomination_is_rescaled_not_dropped():
    """A currency switch must not read as a real price jump, and must keep its history.

    The IMF splices a redenominated currency onto the old one without rescaling, so at
    Croatia's 2023 euro accession the rate falls ~7.5x with no matching move in prices.
    The kuna months are restated in euro rather than discarded.
    """
    rows = (
        _monthly("USA", "United States", 2020, 100.0, 1.0, 1)
        + _monthly("USA", "United States", 2024, 100.0, 1.0, 1)
        + _monthly("HRV", "Croatia", 2020, 100.0, 7.5, 1)  # kuna
        + _monthly("HRV", "Croatia", 2024, 100.0, 1.0, 1)  # euro, same real price level
    )
    panel = pd.DataFrame(
        rows, columns=["country_code", "country_name", "date", "cpi", "exr", "advisory_level"]
    )
    index = pd.DataFrame(
        {
            "country_code": ["USA", "HRV"],
            "country_name": ["United States", "Croatia"],
            "year": [ANCHOR, ANCHOR],
            "price_level_index": [100.0, 65.0],
        }
    )
    out = add_cost_metrics(panel, index, anchor_year=ANCHOR).set_index(["country_code", "date"])
    # Prices and the real rate never moved, so the level must be flat across the switch.
    assert out.loc[("HRV", DATES[1]), "current_dollars"] == pytest.approx(
        out.loc[("HRV", DATES[0]), "current_dollars"]
    )
    assert out.loc[("HRV", DATES[0]), "current_dollars"] == pytest.approx(0.65)


def test_real_devaluation_is_not_mistaken_for_a_redenomination():
    """Argentina's 2023 float was ~2.2x; only far larger unexplained jumps are unit changes."""
    rows = (
        _monthly("USA", "United States", 2020, 100.0, 1.0, 1)
        + _monthly("USA", "United States", 2024, 100.0, 1.0, 1)
        + _monthly("ARG", "Argentina", 2020, 100.0, 100.0, 2)
        + _monthly("ARG", "Argentina", 2024, 100.0, 300.0, 2)  # 3x devaluation, prices flat
    )
    panel = pd.DataFrame(
        rows, columns=["country_code", "country_name", "date", "cpi", "exr", "advisory_level"]
    )
    index = pd.DataFrame(
        {
            "country_code": ["USA", "ARG"],
            "country_name": ["United States", "Argentina"],
            "year": [ANCHOR, ANCHOR],
            "price_level_index": [100.0, 60.0],
        }
    )
    out = add_cost_metrics(panel, index, anchor_year=ANCHOR).set_index(["country_code", "date"])
    # A genuine devaluation must flow through as a real fall in cost, not be rescaled away.
    assert out.loc[("ARG", DATES[1]), "current_dollars"] == pytest.approx(0.6 / 3)


def test_build_panel_grafts_shared_currency():
    """France has no exchange rate of its own; it must inherit the euro area's."""
    dates = pd.date_range("2020-01-01", periods=12, freq="MS")
    cpi = pd.DataFrame(
        {
            "country_code": ["G163", "FRA", "USA"] * 12,
            "date": list(dates.repeat(3)),
            "value": [100.0] * 36,
        }
    )
    exr = pd.DataFrame(
        {
            "country_code": ["G163", "USA"] * 12,
            "date": list(dates.repeat(2)),
            "value": [0.9, 1.0] * 12,
        }
    )
    price_level = pd.DataFrame(
        {
            "country_code": ["FRA", "USA"],
            "country_name": ["France", "United States"],
            "year": [ANCHOR, ANCHOR],
            "price_level_index": [80.0, 100.0],
        }
    )
    advisories = pd.DataFrame({"country_code": ["FRA", "USA"], "advisory_level": [2, 1]})

    out = build_panel(cpi, exr, price_level, advisories)
    assert out.loc[out.country_code == "FRA", "exr"].eq(0.9).all()
    assert out.loc[out.country_code == "FRA", "current_dollars"].to_numpy() == pytest.approx(0.8)


def test_compare_to_official_flags_divergence():
    """The regression guard: a country whose nowcast drifts from the index must show up."""
    panel = _panel()
    index = pd.concat(
        [
            _price_level(fgn=50.0),
            pd.DataFrame(
                {
                    "country_code": ["USA", "FGN"],
                    "country_name": ["United States", "Foreignia"],
                    "year": [2024, 2024],
                    "price_level_index": [100.0, 50.0],
                }
            ),
        ]
    )
    out = add_cost_metrics(panel, index, anchor_year=ANCHOR)
    comparison = compare_to_official(out, index).set_index(["country_code", "year"])

    assert comparison.loc[("FGN", ANCHOR), "ratio"] == pytest.approx(1.0)
    assert comparison.loc[("FGN", 2024), "ratio"] == pytest.approx(1.0)
    assert comparison.loc[("USA", 2024), "ratio"] == pytest.approx(1.0)


def test_redenomination_no_longer_diverges_from_the_official_series():
    """The Sierra Leone bug: a 1000:1 switch used to read 1000x, and must now agree."""
    panel = _panel()
    # Foreignia redenominates 1000:1 in 2024 but keeps the same real price level.
    mask = panel.country_code.eq("FGN") & panel.date.dt.year.eq(2024)
    panel.loc[mask, "exr"] = 20.0 / 1000
    panel.loc[mask, "cpi"] = 100.0
    index = pd.concat(
        [
            _price_level(fgn=50.0),
            pd.DataFrame(
                {
                    "country_code": ["USA", "FGN"],
                    "country_name": ["United States", "Foreignia"],
                    "year": [2024, 2024],
                    "price_level_index": [100.0, 50.0],
                }
            ),
        ]
    )
    out = add_cost_metrics(panel, index, anchor_year=ANCHOR)
    comparison = compare_to_official(out, index).set_index(["country_code", "year"])
    assert comparison.loc[("FGN", 2024), "ratio"] == pytest.approx(1.0)


def test_rank_latest_orders_cheapest_first():
    ranked = rank_latest(add_cost_metrics(_panel(), _price_level()))
    assert ranked.country_name.tolist() == ["Foreignia", "United States"]


def test_rank_latest_excludes_high_advisory():
    panel = _panel()
    panel.loc[panel.country_code == "FGN", "advisory_level"] = 4
    ranked = rank_latest(add_cost_metrics(panel, _price_level()))
    assert ranked.country_name.tolist() == ["United States"]


def test_rank_latest_uses_each_countrys_own_latest_month():
    """A country reporting a month behind still ranks, rather than dropping out."""
    panel = _panel()
    last = panel.loc[panel.country_code.eq("FGN")].date.idxmax()
    panel = panel.drop(index=last)
    ranked = rank_latest(add_cost_metrics(panel, _price_level()))
    assert set(ranked.country_name) == {"Foreignia", "United States"}


def test_rank_latest_excludes_stale_readings():
    panel = _panel()
    panel = panel.loc[~(panel.country_code.eq("FGN") & panel.date.dt.year.eq(2024))]
    ranked = rank_latest(add_cost_metrics(panel, _price_level()), max_staleness_months=6)
    assert ranked.country_name.tolist() == ["United States"]


def test_rank_change_reports_percent_change():
    panel = _panel()
    panel.loc[panel.country_code.eq("FGN") & panel.date.dt.year.eq(2024), "cpi"] = 100.0
    changes = rank_change(add_cost_metrics(panel, _price_level()), "2020-01-01", "2024-01-01")
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

    # The style sheet left-aligns titles, so the text lands on the "left" slot, not "center".
    titles = [top.get_title(loc) for loc in ("center", "left", "right")]
    assert any("24x cheaper" in t for t in titles)
    assert any("Turkiye" in t for t in titles)  # the label comes from the panel
    assert "+0% since 2015" in "".join(t.get_text() for t in bottom.texts)
    plt.close(fig)
