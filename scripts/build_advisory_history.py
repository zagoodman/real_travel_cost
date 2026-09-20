"""Rebuild data/advisory_history.csv from Wayback captures of the State Dept advisory page.

The live feed publishes only current levels, so historical advisory levels have to come from
the Internet Archive. Run this occasionally to extend the series; see docs/advisory-history.md.
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime
import gzip
import html
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

CDX = "https://web.archive.org/cdx/search/cdx"
WAYBACK = "https://web.archive.org/web/{ts}id_/{url}"

# State moved the page in Aug 2025; the old path covers 2017-12 onward, the new one takes over.
PAGE_URLS = (
    "https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories.html",
    "https://travel.state.gov/en/international-travel/travel-advisories.html",
)

# Wayback rejects the default urllib agent the same way travel.state.gov's Cloudflare does.
UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

# 2018 rows read "4: Do not travel"; later ones "Level 4: Do Not Travel".
LEVEL_RE = re.compile(r"(?:Level\s*)?([1-4])\s*:", re.I)
DATE_PATTERNS = (
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"), lambda m: f"{m[1]}-{m[2]}-{m[3]}"),
    (re.compile(r"^(\d{2})/(\d{2})/(\d{4})$"), lambda m: f"{m[3]}-{m[1]}-{m[2]}"),
    (
        re.compile(r"^([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})$"),
        lambda m: (
            datetime.datetime.strptime(f"{m[1]} {m[2]} {m[3]}", "%B %d %Y").date().isoformat()
        ),
    ),
)

# Not a destination, and the country-wide rows that carry per-region levels instead of one level.
NOT_A_COUNTRY = {"destination", "advisory", "worldwide caution"}


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", " ", fragment))).strip()


def _date(cell: str) -> str | None:
    for pattern, fmt in DATE_PATTERNS:
        match = pattern.match(cell)
        if match:
            try:
                return fmt(match)
            except ValueError:
                return None
    return None


def parse_page(source: str) -> list[dict]:
    """Pull (destination, level, issued) out of one captured advisories page."""
    table = re.search(r"<table[^>]*>.*?</table>", source, re.S | re.I)
    if not table:  # 2017-12 through 2018-02 used an accordion, not a table
        return []
    rows = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(0), re.S | re.I):
        cells = [_text(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S | re.I)]
        if len(cells) < 2:
            continue
        name = re.sub(r"\s+Travel Advisory$", "", cells[0]).strip()
        if not name or name.lower() in NOT_A_COUNTRY:
            continue
        level = next((LEVEL_RE.search(c) for c in cells[1:] if LEVEL_RE.search(c)), None)
        issued = next((d for d in (_date(c) for c in cells[1:]) if d), None)
        # "Other" rows (China, Mexico, Israel) have region levels but no national one.
        if level:
            rows.append({"name": name, "level": int(level.group(1)), "issued": issued})
    return rows


def _get(url: str, retries: int = 5) -> bytes:
    delay = 5
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                body = r.read()
            # Wayback serves some captures still gzipped under the id_ (raw) modifier.
            return gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def monthly_snapshots() -> dict[str, tuple[str, str]]:
    """First distinct capture of each month, preferring whichever URL was live then."""
    best: dict[str, tuple[str, str]] = {}
    for url in PAGE_URLS:
        query = f"{CDX}?url={url.split('://')[1]}&output=json&fl=timestamp&filter=statuscode:200&collapse=digest"
        rows = json.loads(_get(query))[1:]
        for (timestamp,) in rows:
            month = timestamp[:6]
            if month not in best or timestamp < best[month][0]:
                best[month] = (timestamp, url)
    return best


def to_intervals(observations: list[dict]) -> list[dict]:
    """Collapse repeated monthly observations into one row per level-run."""
    by_country: dict[str, dict[str, dict]] = collections.defaultdict(dict)
    for obs in observations:
        by_country[obs["name"]][obs["month"]] = obs
    months = sorted({o["month"] for o in observations})
    follows = dict(zip(months, months[1:], strict=False))

    intervals = []
    for name, seen in by_country.items():
        keys = sorted(seen)
        start = keys[0]
        for i, key in enumerate(keys):
            last = i == len(keys) - 1
            changed = not last and seen[keys[i + 1]]["level"] != seen[key]["level"]
            # A missing capture breaks the run: we cannot claim the level held across the gap.
            gap = not last and follows.get(key) != keys[i + 1]
            if last or changed or gap:
                intervals.append(
                    {
                        "name": name,
                        "level": seen[key]["level"],
                        "valid_from": start,
                        "valid_to": "" if last and key == months[-1] else key,
                        "issued": seen[start]["issued"] or "",
                    }
                )
                if not last:
                    start = keys[i + 1]
    intervals.sort(key=lambda r: (r["name"], r["valid_from"]))
    return intervals


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("data/advisory_history.csv"))
    ap.add_argument("--cache", type=Path, default=Path("~/.cache/real_travel_cost/advisory_snaps"))
    ap.add_argument("--since", default="201803", help="earliest YYYYMM to crawl")
    ap.add_argument("--pause", type=float, default=2.0, help="seconds between Wayback fetches")
    ap.add_argument(
        "--refetch", action="store_true", help="discard cached captures for the crawled range"
    )
    args = ap.parse_args()

    cache = args.cache.expanduser()
    cache.mkdir(parents=True, exist_ok=True)

    snapshots = {m: v for m, v in monthly_snapshots().items() if m >= args.since}
    observations = []
    fetched, skipped = [], []
    for month in sorted(snapshots):
        timestamp, url = snapshots[month]
        path = cache / f"{month}.html"
        if args.refetch and path.exists():
            path.unlink()
        if not path.exists() or path.stat().st_size < 50_000:
            path.write_bytes(_get(WAYBACK.format(ts=timestamp, url=url)))
            fetched.append(month)
            time.sleep(args.pause)
        page = parse_page(path.read_text(encoding="utf-8", errors="replace"))
        if not page:
            skipped.append(month)
            continue
        for row in page:
            observations.append({"month": f"{month[:4]}-{month[4:]}-01", **row})

    covered = sorted({o["month"] for o in observations})
    print(f"months covered: {len(covered)} ({covered[0]} .. {covered[-1]})")
    print(f"newly fetched: {len(fetched)}" + (f" -> {', '.join(fetched)}" if fetched else ""))
    if skipped:
        print(f"no table, skipped: {', '.join(skipped)}")

    intervals = to_intervals(observations)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "level", "valid_from", "valid_to", "issued"])
        writer.writeheader()
        writer.writerows(intervals)
    countries = len({r["name"] for r in intervals})
    print(f"{len(observations)} observations -> {len(intervals)} intervals, {countries} countries")


if __name__ == "__main__":
    main()
