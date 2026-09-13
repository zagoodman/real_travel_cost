"""Near-real-time cost of travel abroad, adjusted for exchange rates and inflation."""

from .countries import attach_country_codes, unmatched
from .metrics import add_cost_metrics, build_panel, rank_change, rank_latest
from .pipeline import load_panel
from .plotting import add_legend, plot_devaluation_vs_real_cost, plot_series, use_style
from .sources import fetch_cpi, fetch_exchange_rates, fetch_travel_advisories, load_ppp

__all__ = [
    "add_cost_metrics",
    "add_legend",
    "attach_country_codes",
    "build_panel",
    "fetch_cpi",
    "fetch_exchange_rates",
    "fetch_travel_advisories",
    "load_panel",
    "load_ppp",
    "plot_devaluation_vs_real_cost",
    "plot_series",
    "rank_change",
    "rank_latest",
    "unmatched",
    "use_style",
]
