# Real Travel Cost

Where is it "cheap" to travel internationally? Where is it currently cheaper to travel
compared to previous years?

Answering these questions is challenging because we need to know the prices in a foreign
country adjusting for the exchange rate. The World Bank publishes exactly this, as
[Price level index (GDP)](https://data.worldbank.org/indicator/PA.NUS.GDP.PLI) — the PPP
conversion factor over the market exchange rate, with the US fixed at 100 — but it is
annual and lands with a >1 year lag, which is unhelpful for taking advantage of recent
changes in relative prices.

So this repo takes that index as the anchor and **nowcasts it to the current month** using
monthly IMF inflation and exchange rates. The official series is then a validation target
rather than a thing to reimplement: 97% of country-years since 2023 land within 10% of it.

Note that it may be tempting to examine exchange rates, which are readily available in
real time, and think that a large increase in the dollar-to-foreign-currency exchange
rate implies cheaper travel. Türkiye is the clearest case: since 2015 the dollar has
bought roughly **20x** more lira.

<figure class="image" style="text-align: center">
  <img src="usd-to-lira.png" alt="Turkish lira devaluation against the real cost of travel">
  <figcaption>
    A collapsing currency (top) against what a dollar actually buys (bottom)
  </figcaption>
</figure>

Such a trend does **not** mean holders of dollars can now consume 20x more when visiting
Türkiye. This is because _prices have also increased_ (i.e., inflation), and the two very
nearly cancel. Netting local inflation out, travel to Türkiye is about **40% cheaper**
than in 2015 — a real gain, but a far cry from the 20x the exchange rate implies.

That second panel is the metric this repo computes, for every country, monthly.

## Data

To get as close to real-time data as possible, I use the following sources (all public APIs or included in repo)

1. World Bank API (`api.worldbank.org`): `PA.NUS.GDP.PLI`, the annual price level index
   that anchors the level. `PA.NUS.PRVT.PLI` is the household-consumption basket — closer
   to what a traveler actually buys, ~20 fewer countries — via `load_panel(indicator=...)`.
2. IMF SDMX API (`api.imf.org`), which carries the level forward from the anchor:
   1. `CPI` — country-month consumer price index, 2010 = 100.
   2. `ER` — country-month local-currency-per-USD exchange rates, end of period.
3. State Department travel advisory RSS: current advisory levels (1 to 4). This is a
   snapshot of today's levels, not a history, so the advisory filter is not a historical
   control when ranking changes over past years.

## Usage

```bash
uv sync --extra notebook
uv run jupyter lab notebooks/real-travel-cost.ipynb
```

```python
import real_travel_cost as rtc

panel = rtc.load_panel()  # fetches once, then caches to ~/.cache/real_travel_cost
rtc.rank_latest(panel).head(10)  # cheapest countries at advisory level 1-2
rtc.rank_change(panel, "2015-07-01", "2025-07-01")
```

`load_panel()` returns one row per country-month. The headline column is `current_dollars`:
the dollars needed abroad to buy what $1 buys in the US today, so below 1.0 means a dollar
goes further there. The US is exactly 1.0 by construction, since the World Bank fixes it at
100 in every year of the anchor.

To check the nowcast against the published series:

```python
rtc.compare_to_official(panel, rtc.fetch_price_level_index(), since=2023)
```

`ratio` is 1.0 where they agree. Agreement decays with distance from the anchor year — 97%
of country-years within 10% since 2023, 81% since 2015 — which is the honest limit of
extrapolating a monthly series away from an annual benchmark. `uv run pytest -m network`
asserts it as a regression test.

Regenerate the README figure with `rtc.plot_devaluation_vs_real_cost(panel)`, which takes
any `country_code` and defaults to Türkiye.

## Development

```bash
uv run pytest
uv run ruff check .
```
