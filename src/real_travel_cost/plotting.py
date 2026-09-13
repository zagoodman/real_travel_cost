"""Shared matplotlib style and the handful of plots the analysis uses."""

from __future__ import annotations

from importlib import resources

import matplotlib as mpl
import matplotlib.ticker as mtick
import pandas as pd
from matplotlib import pyplot as plt

LOCAL, BASELINE = "#BA4F4F", "#25636F"  # local country vs the US reference


def use_style() -> None:
    """Apply the repo's matplotlib style sheet."""
    plt.style.use(str(resources.files("real_travel_cost.data") / "plotting.mplstyle"))


def add_legend(title: str | None = None) -> None:
    """Legend outside the axes, vertically centered."""
    plt.legend(loc="center left", bbox_to_anchor=(1, 0.5), title=title)


def plot_series(
    panel: pd.DataFrame,
    countries: list[str],
    metric: str = "current_dollars",
    title: str | None = None,
    as_percent: bool = True,
    ax: plt.Axes | None = None,
) -> plt.Axes:
    """One line per country of `metric` over time."""
    if ax is None:
        _, ax = plt.subplots()

    for country in countries:
        subset = panel.loc[panel.country_name == country]
        ax.plot(subset.date, subset[metric], label=country)

    if as_percent:
        ax.yaxis.set_major_formatter(mpl.ticker.PercentFormatter(xmax=1, decimals=0))
        ax.set_ylim(0)

    plt.sca(ax)
    add_legend()
    if title:
        ax.set_title(title)
    return ax


def plot_devaluation_vs_real_cost(
    panel: pd.DataFrame,
    country_code: str = "TUR",
    country_label: str = "Turkiye",
    start: str = "2015-01-01",
) -> plt.Figure:
    """The README figure: a collapsing currency above, the far smaller real gain below."""
    since = pd.Timestamp(start)
    local = panel[(panel.country_code == country_code) & (panel.date >= since)].set_index("date")

    rate = local.exr / local.exr.iloc[0]
    cost = local.current_dollars
    multiple = rate.iloc[-1]
    change = cost.iloc[-1] / cost.iloc[0] - 1

    fig, (top, bottom) = plt.subplots(
        2,
        1,
        figsize=(11, 8.5),
        sharex=True,
        gridspec_kw={"height_ratios": [1, 1.15], "hspace": 0.3},
    )

    top.plot(rate.index, rate, color=LOCAL)
    top.set_title(f"The exchange rate alone suggests {country_label} got {multiple:.0f}x cheaper")
    top.set_ylabel(f"Local currency per dollar ({since.year} = 1x)")
    top.yaxis.set_major_locator(mtick.MultipleLocator(5))
    top.yaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: f"{v:.0f}x"))
    top.set_ylim(0, multiple * 1.3)
    _annotate_end(top, rate.index[-1], multiple, f"{multiple:.1f}x more local currency per dollar")

    # The US is 1.0 by construction, so it reads as a reference line rather than a series.
    bottom.axhline(1.0, color=BASELINE, linewidth=2)
    bottom.annotate(
        "United States",
        xy=(cost.index[0], 1.0),
        xytext=(6, 8),
        textcoords="offset points",
        color=BASELINE,
        fontweight="semibold",
    )
    bottom.plot(cost.index, cost, color=LOCAL)
    bottom.set_title("Adjusted for local inflation, the real gain is far smaller")
    bottom.set_ylabel("Cost of $1 of US goods")
    bottom.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=1, decimals=0))
    bottom.set_ylim(0, 1.25)
    _annotate_end(
        bottom, cost.index[-1], cost.iloc[-1], f"{country_label}, {change:+.0%} since {since.year}"
    )

    fig.text(
        0.5,
        0.04,
        f"Sources: IMF CPI and exchange rates, World Bank PPP. Through {panel.date.max():%B %Y}.",
        ha="center",
        fontsize=9,
        color="#666666",
    )
    return fig


def _annotate_end(ax: plt.Axes, x, y, text: str) -> None:
    """Label a series above its final point, inset from the right edge."""
    ax.annotate(
        text,
        xy=(x, y),
        xytext=(-8, 14),
        textcoords="offset points",
        ha="right",
        color=LOCAL,
        fontweight="semibold",
    )
