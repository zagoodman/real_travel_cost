"""One-call fetch of every source into the finished panel, with on-disk caching."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .countries import attach_country_codes, canonicalize_names
from .metrics import build_panel
from .sources import (
    PLI_GDP,
    fetch_cpi,
    fetch_exchange_rates,
    fetch_price_level_index,
    fetch_travel_advisories,
)

DEFAULT_CACHE = Path("~/.cache/real_travel_cost").expanduser()
CACHE_FILENAME = "panel.parquet"


def load_panel(
    refresh: bool = False,
    cache_dir: Path | str | None = DEFAULT_CACHE,
    indicator: str = PLI_GDP,
) -> pd.DataFrame:
    """Return the country-month panel, refetching only when asked or uncached.

    The IMF pulls cover every country back to 2000 and take minutes, hence the cache.
    """
    cache_path = Path(cache_dir).expanduser() / CACHE_FILENAME if cache_dir else None
    if cache_path and cache_path.exists() and not refresh:
        return pd.read_parquet(cache_path)

    price_level = canonicalize_names(fetch_price_level_index(indicator))
    panel = build_panel(
        cpi=fetch_cpi(),
        exchange_rates=fetch_exchange_rates(),
        price_level=price_level,
        advisories=attach_country_codes(fetch_travel_advisories(), price_level),
    )

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        panel.to_parquet(cache_path, index=False)
    return panel
