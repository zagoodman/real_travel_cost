# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Answers: where is it currently cheap to travel, and where has it gotten cheaper than in past
years? Exchange rates alone mislead — a currency that devalues 500% usually inflated domestically
too. The World Bank's PPP-to-market-exchange-rate ratio captures this but lags >1 year, so this
repo rebuilds a near-real-time version from monthly IMF data. See README.md for the full argument.

## Commands

```bash
uv sync --extra notebook     # create .venv and install, including the Jupyter kernel
uv run pytest                # all tests; they never hit the network
uv run pytest tests/test_metrics.py::test_us_baseline_is_one_dollar_per_dollar
uv run ruff check . --fix
uv run ruff format .
uv run jupyter lab notebooks/real-travel-cost.ipynb
```

## Layout

- `src/real_travel_cost/sources.py` — fetchers, one per upstream feed, plus endpoint constants.
- `countries.py` — the three hand-maintained tables: `ADVISORY_NAME_TO_CODE`,
  `SHARED_CURRENCIES`, `REDENOMINATED`.
- `metrics.py` — `build_panel` (joins) and `add_cost_metrics` (the metric chain), plus rankings.
- `pipeline.py` — `load_panel`, the one-call fetch with a parquet cache under `~/.cache/`.
- `plotting.py` — style loading and the line plot.
- `data/` — packaged `ppp2020.csv` (used), `ppp2017.csv` (legacy), `plotting.mplstyle`. Read via
  `importlib.resources`, so nothing depends on the CWD.
- `notebooks/real-travel-cost.ipynb` — demo only. Analysis logic belongs in the package.
- `2023-11-01 Exchange Rates.ipynb` — the original one-file version, superseded, kept for
  reference. It targets an IMF API that no longer exists and will not run.

## Data sources (live HTTP, no keys)

IMF SDMX 2.1 at `https://api.imf.org/external/sdmx/2.1`, agency `IMF.STA`:

- `CPI` flow, key `.CPI._T.IX.M` — all-items index, 2010 = 100. Dimensions are positional:
  `COUNTRY.INDEX_TYPE.COICOP_1999.TYPE_OF_TRANSFORMATION.FREQUENCY`.
- `ER` flow, key `.XDC_USD.EOP_RT.M` — **local currency per USD**, end of period. Dimensions:
  `COUNTRY.INDICATOR.TYPE_OF_TRANSFORMATION.FREQUENCY`. Note `USD_XDC` is the inverse; don't
  reach for it by mistake.

Data requests need the `Accept: application/vnd.sdmx.structurespecificdata+xml;version=2.1`
header or the response comes back empty. Structure queries live under `/datastructure/IMF.STA/`
and use DSD ids (`DSD_CPI`, `DSD_ER_PUB`), which differ from the dataflow ids.

The State Dept. feed is the RSS at `travel.state.gov/_res/rss/TAsTWs.xml`. Its Cloudflare rejects
the default `requests` user agent, hence `BROWSER_HEADERS`. The old `cadatacatalog.state.gov` XML
now 403s.

## Country identity

IMF data is keyed on ISO-3, and so are the bundled PPP files, so those join directly — no name
mapping. Only the State Dept. feed is name-only; `attach_country_codes` maps it via
`ADVISORY_NAME_TO_CODE` then an exact-name fallback, and `unmatched()` lists what got no code.
Joins are inner, so an unmapped country drops out silently rather than erroring.

Two adjustments are load-bearing and easy to miss:

- `SHARED_CURRENCIES` grafts an issuer's rate onto countries with no series of their own — the
  euro area is `G163`, and the Danish krone covers Greenland and the Faroes.
- `REDENOMINATED` drops months after a currency switch, where the PPP factor is still quoted in
  the old unit. Croatia (kuna → euro, 2023) otherwise reads ~4x US prices. Any future euro
  accession needs an entry here *and* in `SHARED_CURRENCIES`.

## The metric chain

`add_cost_metrics` builds these in order, each layering one adjustment onto the last:

1. `cpi_rebased` — CPI with each country's 2020 = 100, matching the PPP base year. Countries
   whose series starts after 2020 (Australia's monthly CPI begins 2024) cannot be rebased and are
   dropped rather than carried as NaN.
2. `ppp_dollars` = `ppp / exr` — moves only with the exchange rate.
3. `real_dollars` = `cpi_rebased * ppp_dollars` — adds local inflation; in 2020 dollars.
4. `current_dollars` = `real_dollars / us_cpi` — deflated by the US series, so it is in today's
   dollars. **Headline metric**: lower = cheaper for a dollar holder, and the US is 1.0 by
   construction. Both ranking helpers use it.

Countries publish CPI on different lags. The US deflator is joined with `merge_asof` (not an
equality join) so a country is not dropped for a month the US has not published, and
`rank_latest` takes each country at its own most recent month subject to `max_staleness_months`.
Both default to advisory level <= 2.

## Conventions

- Comments are one line and explain *why*; the code says what. Don't narrate steps.
- `ruff` (line length 100) is the formatter — no Black.
- Tests assert against a hand-built panel with known answers, never live data. Changing the
  metric chain means updating `tests/test_metrics.py`.
- Sanity check after touching the chain: the US must come out exactly 1.0, and no country should
  exceed ~1.5 — a large outlier means a currency mismatch, not a finding.
