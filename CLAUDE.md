# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Answers: where is it currently cheap to travel, and where has it gotten cheaper than in past
years? Exchange rates alone mislead — a currency that devalues 500% usually inflated domestically
too. The World Bank's price level index captures this but lags >1 year, so this repo anchors on
that official series and nowcasts it to the current month with monthly IMF data. See README.md
for the full argument.

## Commands

```bash
uv sync --extra notebook     # create .venv and install, including the Jupyter kernel
uv run pytest                # offline tests only; network ones are deselected by default
uv run pytest -m network      # agreement against the live World Bank series
uv run pytest tests/test_metrics.py::test_us_baseline_is_one_dollar_per_dollar
uv run ruff check . --fix
uv run ruff format .
uv run jupyter lab notebooks/real-travel-cost.ipynb
```

## Layout

- `src/real_travel_cost/sources.py` — fetchers, one per upstream feed, plus endpoint constants.
- `countries.py` — the hand-maintained tables: `ADVISORY_NAME_TO_CODE`, `CANONICAL_NAMES`,
  `SHARED_CURRENCIES`.
- `metrics.py` — `build_panel` (joins), `add_cost_metrics` (the metric chain), rankings, and
  `compare_to_official` (the nowcast against the published series).
- `pipeline.py` — `load_panel`, the one-call fetch with a parquet cache under `~/.cache/`.
- `plotting.py` — style loading and the line plot.
- `data/` — packaged `plotting.mplstyle`, read via `importlib.resources`, so nothing depends on
  the CWD. The PPP CSVs are gone; the level now comes from the live World Bank API.
- `notebooks/real-travel-cost.ipynb` — demo only. Analysis logic belongs in the package.
- `2023-11-01 Exchange Rates.ipynb` — the original one-file version, superseded, kept for
  reference. It targets an IMF API that no longer exists and will not run.

## Data sources (live HTTP, no keys)

World Bank at `https://api.worldbank.org/v2`, indicator `PA.NUS.GDP.PLI` ("Price level index
(GDP)") — the PPP-to-exchange-rate ratio, US = 100 in every year, annual. One request returns
the whole series; `fetch_price_level_index` raises if it ever paginates. `PA.NUS.PRVT.PLI` is
the household-consumption basket, a better fit for a traveler but ~20 fewer countries. The
World Bank spells Kosovo `XKX` where the rest of the repo uses `KSV`, and ships
statistical-yearbook names ("Slovak Republic", "Viet Nam") that `CANONICAL_NAMES` overrides.

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
now 403s. It serves UTF-8 while declaring ISO-8859-1, so `response.encoding` is forced or
"Curaçao" arrives as mojibake, and titles carry non-breaking spaces and curly apostrophes that
`_clean_title` normalizes. It publishes only current levels — there is no history in it.

Historical levels come instead from Wayback captures of the advisories HTML page, built by
`scripts/build_advisory_history.py` into `data/advisory_history.csv` (one row per country per
level-run, 2018-03 onward). That table is not fetched by `load_panel`; refresh it on its own.
See `docs/advisory-history.md` for the schema, the refresh command and the parsing gotchas.

## Country identity

IMF and World Bank data are both keyed on ISO-3, so they join directly — no name mapping. Only
the State Dept. feed is name-only; `attach_country_codes` maps it via `ADVISORY_NAME_TO_CODE`
then an exact-name fallback against the index's names, and `unmatched()` lists what got no code.
Joins are inner, so an unmapped country drops out silently rather than erroring — which is how
Türkiye went missing once the name fallback started seeing "Turkiye" instead of "Turkey".
The ~16 names still unmatched are territories with no IMF monthly CPI, so they would drop anyway.

Three adjustments are load-bearing and easy to miss:

- `CANONICAL_NAMES` replaces World Bank labels with current unabbreviated forms, keyed on ISO-3
  so an upstream relabelling cannot quietly restore the old spelling. It drives both display and
  advisory name matching, so adding an entry can change which advisories match.
- `SHARED_CURRENCIES` grafts an issuer's rate onto countries with no series of their own — the
  euro area is `G163`, and the Danish krone covers Greenland and the Faroes.
- `_rescale_across_redenominations` detects currency switches from the data instead of a table.
  The IMF splices a redenominated currency onto the old one without rescaling, so the rate falls
  sharply with no matching CPI move; the older months are multiplied back onto the current unit.
  This is direction-sensitive: only a *fall* past `REDENOMINATION_JUMP` counts, because a
  redenomination strengthens the unit per USD while a devaluation weakens it. The five euro
  accessions in the panel span 3.2x (Lithuania) to 340x (Greece), and no genuine market move
  comes close, so a future accession needs no code change — only a `SHARED_CURRENCIES` entry.

## The metric chain

`add_cost_metrics` anchors on the published index, then carries it forward:

1. Exchange rates are restated in each country's current currency unit (see above).
2. `local_in_usd` = `cpi / exr` — local prices in dollars, correct up to an unknown
   country-specific constant, which is what the anchor supplies.
3. `relative_prices` = `local_in_usd / us_cpi` — the same, measured against US prices.
4. `calibration` — per country, the anchor year's published index over its mean
   `relative_prices`. This is the constant that turns a ratio into an index level.
5. `price_level_nowcast` = `relative_prices * calibration`, and `current_dollars` is that over
   100. **Headline metric**: lower = cheaper for a dollar holder, the US is exactly 1.0 because
   the World Bank fixes it at 100, and the anchor year reproduces the official value by
   construction. Both ranking helpers use it.

The anchor year is the latest year present in both the index and a full 12 months of monthly
data (`_anchor_year`), so it moves forward on its own as the World Bank publishes. A country
needs both an anchor level and a complete anchor year, or it is dropped rather than carried
as NaN.

Accuracy is a function of distance from the anchor, and `compare_to_official` measures it:
97% of country-years within 10% since 2023, 90% since 2020, 81% since 2015. The far past is
genuinely weaker (Libya, Burundi drift 2-3x by 2010), which is extrapolation error, not a unit
bug — a unit bug shows as an order-of-magnitude jump and trips the network test.

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
  exceed ~1.5 (Iceland is the current top at ~1.27) — a large outlier means a currency mismatch,
  not a finding. `uv run pytest -m network` checks this against the official series.
