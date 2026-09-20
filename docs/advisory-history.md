# Travel advisory history

`data/advisory_history.csv` holds State Dept. travel advisory levels over time: one row per
country per level-run, 2018-03 to present. The live feed publishes only *current* levels, so the
history is reconstructed from Internet Archive captures of the advisories page.

## Schema

| column | meaning |
| --- | --- |
| `name` | destination as State spells it — needs `ADVISORY_NAME_TO_CODE` to reach ISO-3 |
| `level` | 1–4, the advisory level held across this interval |
| `valid_from` | first month observed at this level (`YYYY-MM-01`) |
| `valid_to` | last month observed at this level; **empty means still current** |
| `issued` | date State stamped on the advisory that opened the interval |

`issued` precedes `valid_from` by a median of 15 days (p90 50): it is the real change date, while
`valid_from` is when monthly sampling first saw it. Use `issued` when you want the sharper
boundary, `valid_from` when joining to a month-granularity panel.

Intervals never overlap and are split rather than bridged across a missing capture, so a gap in
Wayback coverage shows up as two adjacent runs at the same level instead of an invented
continuous one.

## Refreshing

Run this monthly or quarterly; it appends new months and rewrites the CSV in place.

```bash
uv run python scripts/build_advisory_history.py
```

It prints what it did, and that output is the check on whether the run was worth committing:

```
months covered: 101 (2018-03-01 .. 2026-07-01)
newly fetched: 2 -> 202608, 202609
21312 observations -> 1587 intervals, 261 countries
```

- `newly fetched: 0` means every month was already cached — the CSV will be unchanged, so there
  is nothing to commit. This is the normal result of running twice in a row.
- `months covered` should end at last month or the one before. If it lags further, Wayback has
  not captured the page recently; wait rather than chasing it.
- `no table, skipped: ...` naming a *recent* month means the page layout changed and `parse_page`
  needs a fourth format. For 2017-12 through 2018-02 it is expected and permanent.
- A country count far off 261, or an interval count that jumps by hundreds, means a parse
  regression rather than real news — diff the CSV before committing.

Then sanity-check the diff and commit `data/advisory_history.csv`:

```bash
git diff --stat data/advisory_history.csv
```

A normal month touches a handful of rows: some open-ended rows gain a `valid_to`, and new
open-ended rows appear beneath them. Wholesale rewrites are a red flag.

### Options

```bash
uv run python scripts/build_advisory_history.py --since 202501   # limit the crawled range
uv run python scripts/build_advisory_history.py --refetch --since 202601   # force refetch
uv run python scripts/build_advisory_history.py --pause 5        # gentler on Wayback
```

`--since` narrows which months are crawled but does **not** refetch ones already cached; pair it
with `--refetch` when a month parsed badly and you want its capture pulled again. Note that
`--since` also truncates the output CSV to that range, so use it for diagnosis and run without it
to regenerate the committed table.

Captures are cached under `~/.cache/real_travel_cost/advisory_snaps/`, one HTML file per month.
A cold crawl is ~104 requests at `--pause 2`, roughly twelve minutes; incremental runs are
seconds. **This is deliberately not wired into `load_panel()`** — it hits a third-party archive
and would make the ordinary fetch path slow and rate-limit-prone.

Missing a month costs nothing: Wayback keeps the captures, so a later run picks it up.

## Gotchas

- **Series starts 2018-03.** The four-level system launched Jan 2018, and 2017-12 through 2018-02
  render the list as an accordion rather than a table, so the parser skips them. Anything earlier
  does not exist in this form at all — do not backfill it; a pre-2018 "level" would be fabricated.
- **Three page formats.** 2018 rows read `4: Do not travel` with ISO dates; later ones
  `Level 4: Do Not Travel` with `August 6, 2020`; the post-2025 page uses `MM/DD/YYYY` and moves
  the destination into a `<th>`. `parse_page` handles all three — check it before assuming a new
  capture is simply broken.
- **Wayback serves some captures gzipped** even under the `id_` raw modifier, with no
  `Content-Encoding` header to warn you. `_get` sniffs the magic bytes.
- **`Other` rows are dropped, not missing data.** China, Mexico and Israel periodically carry
  per-region levels instead of one national level; those months have no country-wide number.
  This is the gap `MANUAL_ADVISORIES` fills for the current month — that table must not be applied
  to historical rows, or it would stamp today's judgment onto every past date.
- **261 names, not all countries.** Sub-national and grouped entries ("Jerusalem",
  "French West Indies") will not match an ISO-3 code and drop out on the join, as intended.
- **2020–2022 levels are globally elevated.** Mean level runs 1.60 (2018) → 3.65 (mid-2021) →
  1.93 (now). An `advisory_level <= 2` filter legitimately excludes most of the world across the
  COVID window; that is the source data, not a bug.
