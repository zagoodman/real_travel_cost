"""Fetchers for the upstream datasets. All public, no API keys."""

from __future__ import annotations

import datetime
import html
import re
import time

import pandas as pd
import requests

SDMX_BASE = "https://api.imf.org/external/sdmx/2.1"
SDMX_AGENCY = "IMF.STA"
SDMX_DATA_HEADERS = {"Accept": "application/vnd.sdmx.structurespecificdata+xml;version=2.1"}

STATE_DEPT_URL = "https://travel.state.gov/_res/rss/TAsTWs.xml"

WORLD_BANK_BASE = "https://api.worldbank.org/v2"

# Price level index: PPP conversion factor over market exchange rate, US = 100. The GDP
# basket is the series the README cites; the household one is closer to what a traveler
# buys but covers ~20 fewer countries.
PLI_GDP = "PA.NUS.GDP.PLI"
PLI_HOUSEHOLD = "PA.NUS.PRVT.PLI"

# The World Bank quotes Kosovo as XKX; IMF data and the advisory table use KSV.
WORLD_BANK_CODE_FIXES = {"XKX": "KSV"}

# travel.state.gov sits behind Cloudflare, which rejects the default requests user agent.
BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# "Peru - Level 2: Exercise Increased Caution", optionally with an interstitial note
# ("... - See Summaries - Level 2"). The separator must be a spaced hyphen: "Guinea-Bissau"
# and "Timor-Leste" carry an unspaced one inside the name itself.
ADVISORY_TITLE = re.compile(r"^(?P<country>.+?)\s+-\s+(?:[^-]*?\s+-\s+)?Level\s*(?P<level>[1-4])")

# Dataflow keys are positional: see the DSD dimension order in each fetcher below.
CPI_FLOW = "CPI"  # COUNTRY.INDEX_TYPE.COICOP_1999.TYPE_OF_TRANSFORMATION.FREQUENCY
ER_FLOW = "ER"  # COUNTRY.INDICATOR.TYPE_OF_TRANSFORMATION.FREQUENCY

EURO_AREA_CODE = "G163"

# State issues no advisory for the US, but it is the baseline the whole index is built on,
# so an inner join would drop it.
US_ADVISORY_LEVEL = 1

DEFAULT_TIMEOUT = 300

# The feed is served from inconsistent cache nodes; read it a few times and take the mode.
FEED_READS = 3

# travel.state.gov serves mid-rebuild prefixes of the feed that parse cleanly but drop items.
# A complete body carries every destination, so require an item count near the known total
# rather than a byte size, which moves as advisory text is edited.
MIN_FEED_ITEMS = 200

# travel.state.gov rate-limits repeated reads; space them and back off on a 429.
FEED_READ_PAUSE = 5.0


def _fetch_sdmx(flow: str, key: str, start_period: int, timeout: int) -> pd.DataFrame:
    """Return long-format country/date/value rows for one SDMX series key."""
    url = f"{SDMX_BASE}/data/{SDMX_AGENCY},{flow}/{key}?startPeriod={start_period}"
    response = requests.get(url, headers=SDMX_DATA_HEADERS, timeout=timeout)
    response.raise_for_status()

    rows = []
    for series in re.finditer(r"<Series\b([^>]*)>(.*?)</Series>", response.text, re.S):
        country = re.search(r'COUNTRY="([^"]+)"', series.group(1)).group(1)
        for obs in re.finditer(r'TIME_PERIOD="([^"]+)"\s+OBS_VALUE="([^"]+)"', series.group(2)):
            rows.append((country, obs.group(1), obs.group(2)))

    frame = pd.DataFrame(rows, columns=["country_code", "period", "value"])
    frame["date"] = pd.to_datetime(frame.period.str.replace("M", "", regex=False), format="%Y-%m")
    frame["value"] = pd.to_numeric(frame.value, errors="coerce")
    return frame[["country_code", "date", "value"]].dropna(subset=["value"])


def fetch_cpi(start_period: int = 2000, timeout: int = DEFAULT_TIMEOUT) -> pd.DataFrame:
    """Monthly all-items consumer price index by country, 2010 = 100."""
    return _fetch_sdmx(CPI_FLOW, ".CPI._T.IX.M", start_period, timeout)


def fetch_exchange_rates(start_period: int = 2000, timeout: int = DEFAULT_TIMEOUT) -> pd.DataFrame:
    """Monthly local currency per USD by country, end of period."""
    return _fetch_sdmx(ER_FLOW, ".XDC_USD.EOP_RT.M", start_period, timeout)


def _clean_title(title: str) -> str:
    """Unescape entities and normalize the feed's stray Unicode spaces to plain ones."""
    # Titles carry non-breaking and narrow no-break spaces plus curly apostrophes, all of
    # which defeat exact name matching.
    text = html.unescape(title)
    for space in ("\u00a0", "\u202f", "\u2009"):
        text = text.replace(space, " ")
    return text.replace("\u2019", "'").strip()


def _pub_date(raw: str) -> str | None:
    """RSS pubDate ("Fri, 04 Sep 2026") to ISO; this is State's own stamp, not our read time."""
    text = _clean_title(raw).split(",", 1)[-1].strip()
    for fmt in ("%d %b %Y %H:%M:%S %z", "%d %b %Y"):
        try:
            return datetime.datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _slug_rank(name: str, slug: str) -> int:
    """Prefer the advisory whose URL names the destination itself over a bundled region."""
    stem = slug.replace(".html", "").replace("-travel-advisory", "").strip("1")
    # "Mainland China, ..." -> "mainland china" -> the china-travel-advisory row, not Macau's.
    head = re.split(r"[,(]", name)[0].lower().replace("mainland ", "").strip()
    return 0 if stem.replace("-", " ") == head else 1


def _parse_one_feed(text: str) -> pd.DataFrame:
    """Rows of (country_name, advisory_level, issued) from one feed body."""
    rows = []
    for item in re.findall(r"<item>(.*?)</item>", text, re.S):
        title = re.search(r"<title>(.*?)</title>", item, re.S)
        link = re.search(r"<link>(.*?)</link>", item, re.S)
        published = re.search(r"<pubDate>(.*?)</pubDate>", item, re.S)
        if not title:
            continue
        match = ADVISORY_TITLE.match(_clean_title(title.group(1)))
        if match:
            slug = link.group(1).strip().rsplit("/", 1)[-1] if link else ""
            rows.append(
                (
                    match.group("country"),
                    int(match.group("level")),
                    slug,
                    _pub_date(published.group(1)) if published else None,
                )
            )

    advisories = pd.DataFrame(rows, columns=["country_name", "advisory_level", "slug", "issued"])
    pairs = zip(advisories.country_name, advisories.slug, strict=True)
    advisories["rank"] = [_slug_rank(name, slug) for name, slug in pairs]
    # A grouped destination shares one title across several advisories that differ in level
    # ("Mainland China, Hong Kong & Macau" covers mainland at 2, Macau at 3), so the title
    # cannot disambiguate them; the link slug names which one each row is.
    advisories = advisories.sort_values("rank").drop_duplicates("country_name", keep="first")
    return advisories[["country_name", "advisory_level", "issued"]]


def fetch_travel_advisories(
    timeout: int = DEFAULT_TIMEOUT, reads: int = FEED_READS
) -> pd.DataFrame:
    """State Dept. advisory level 1-4, with the date State stamped on each advisory.

    travel.state.gov regenerates the feed continuously and serves partial builds, so two
    reads seconds apart can disagree on a level or omit a country entirely. Reading it
    `reads` times and taking each country's modal level makes a single run reproducible;
    `feed_last_modified` on the result records which upstream build won.
    """
    frames, stamps, sizes = [], [], []
    for attempt in range(max(1, reads)):
        if attempt:
            time.sleep(FEED_READ_PAUSE)
        response = requests.get(STATE_DEPT_URL, headers=BROWSER_HEADERS, timeout=timeout)
        if response.status_code == 429:
            time.sleep(FEED_READ_PAUSE * 4)
            response = requests.get(STATE_DEPT_URL, headers=BROWSER_HEADERS, timeout=timeout)
        response.raise_for_status()
        # The feed serves UTF-8 but declares ISO-8859-1, which turns "Curaçao" into mojibake.
        response.encoding = "utf-8"
        frames.append(_parse_one_feed(response.text))
        stamps.append((response.headers.get("Last-Modified"), len(response.content)))
        sizes.append(len(response.content))

    # A mid-rebuild response is a prefix of the real feed: it parses cleanly but silently
    # omits whole items, which reads as "this country has no advisory" rather than an error.
    whole = [f for f in frames if len(f) >= MIN_FEED_ITEMS]
    if not whole:
        raise RuntimeError(
            f"every read of {STATE_DEPT_URL} was truncated "
            f"(largest {max(len(f) for f in frames)} items, need {MIN_FEED_ITEMS})"
        )
    frames = whole

    combined = pd.concat(frames, ignore_index=True)
    # Ties go to the more cautious level, so a flap never silently lowers a warning.
    ranked = (
        combined.groupby(["country_name", "advisory_level"], as_index=False)
        .agg(seen=("advisory_level", "size"), issued=("issued", "first"))
        .sort_values(["seen", "advisory_level"], ascending=[False, False])
    )
    advisories = ranked.drop_duplicates("country_name", keep="first")
    advisories = advisories[["country_name", "advisory_level", "issued"]]

    us = pd.DataFrame([("United States", US_ADVISORY_LEVEL, None)], columns=advisories.columns)
    advisories = pd.concat([advisories, us]).reset_index(drop=True)
    advisories.attrs["observed_at"] = datetime.datetime.now(datetime.UTC).isoformat(
        timespec="seconds"
    )
    advisories.attrs["feed_last_modified"] = stamps[-1][0]
    advisories.attrs["feed_bytes"] = stamps[-1][1]
    advisories.attrs["feed_reads"] = len(frames)
    advisories.attrs["feed_reads_discarded"] = len(sizes) - len(frames)
    return advisories


def fetch_price_level_index(
    indicator: str = PLI_GDP, timeout: int = DEFAULT_TIMEOUT
) -> pd.DataFrame:
    """Annual World Bank price level index by country, US = 100 in every year.

    This is the published version of what this repo nowcasts: it already divides the PPP
    conversion factor by the market exchange rate, so it needs no unit handling and is
    rebased by the World Bank whenever a currency is redenominated.
    """
    url = f"{WORLD_BANK_BASE}/country/all/indicator/{indicator}"
    response = requests.get(url, params={"format": "json", "per_page": 25000}, timeout=timeout)
    response.raise_for_status()
    payload = response.json()

    # The first element is pagination metadata; a single page holds the whole series.
    meta, rows = payload[0], payload[1]
    if meta["pages"] > 1:  # guard against the series outgrowing one request
        raise RuntimeError(f"{indicator} returned {meta['pages']} pages; raise per_page")

    frame = pd.DataFrame(
        [
            (row["countryiso3code"], row["country"]["value"], row["date"], row["value"])
            for row in rows
            if row["value"] is not None and row["countryiso3code"]
        ],
        columns=["country_code", "country_name", "year", "price_level_index"],
    )
    frame["country_code"] = frame.country_code.replace(WORLD_BANK_CODE_FIXES)
    frame["year"] = frame.year.astype(int)
    return frame.sort_values(["country_code", "year"]).reset_index(drop=True)
