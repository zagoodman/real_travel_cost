"""Fetchers for the three upstream datasets. All public, no API keys."""

from __future__ import annotations

import html
import re
from importlib import resources

import pandas as pd
import requests

SDMX_BASE = "https://api.imf.org/external/sdmx/2.1"
SDMX_AGENCY = "IMF.STA"
SDMX_DATA_HEADERS = {"Accept": "application/vnd.sdmx.structurespecificdata+xml;version=2.1"}

STATE_DEPT_URL = "https://travel.state.gov/_res/rss/TAsTWs.xml"

# travel.state.gov sits behind Cloudflare, which rejects the default requests user agent.
BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# "Peru - Level 2: Exercise Increased Caution"; country may itself contain " - ".
ADVISORY_TITLE = re.compile(r"^(?P<country>.+?)\s*-\s*(?:[^-]*-\s*)?Level (?P<level>[1-4])")

# Dataflow keys are positional: see the DSD dimension order in each fetcher below.
CPI_FLOW = "CPI"  # COUNTRY.INDEX_TYPE.COICOP_1999.TYPE_OF_TRANSFORMATION.FREQUENCY
ER_FLOW = "ER"  # COUNTRY.INDICATOR.TYPE_OF_TRANSFORMATION.FREQUENCY

EURO_AREA_CODE = "G163"

# Advisory levels for countries the State Dept. feed omits or formats unusually.
MANUAL_ADVISORIES = {
    "China": 3,
    "Mexico": 2,
    "Israel": 2,
    "United States": 1,
    "Vietnam": 1,
}

DEFAULT_TIMEOUT = 300


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


def fetch_travel_advisories(timeout: int = DEFAULT_TIMEOUT) -> pd.DataFrame:
    """State Dept. advisory level 1-4, parsed out of the RSS item titles."""
    response = requests.get(STATE_DEPT_URL, headers=BROWSER_HEADERS, timeout=timeout)
    response.raise_for_status()

    rows = []
    for title in re.findall(r"<title>(.*?)</title>", response.text, re.S):
        match = ADVISORY_TITLE.match(html.unescape(title).strip())
        if match:
            rows.append((match.group("country"), int(match.group("level"))))

    advisories = pd.DataFrame(rows, columns=["country_name", "advisory_level"])
    manual = pd.DataFrame(MANUAL_ADVISORIES.items(), columns=["country_name", "advisory_level"])
    advisories = pd.concat([advisories, manual])
    # Keep the first listing per country: multi-country titles repeat at several levels.
    return advisories.drop_duplicates("country_name", keep="first").reset_index(drop=True)


def load_ppp(year: int = 2020) -> pd.DataFrame:
    """World Bank PPP conversion factor (local currency per international dollar)."""
    path = resources.files("real_travel_cost.data") / f"ppp{year}.csv"
    ppp = pd.read_csv(path, encoding="utf-8-sig")
    ppp = ppp.rename(columns={f"ppp_{year}": "ppp"})
    ppp["ppp"] = ppp.ppp.astype(float)
    return ppp[["country_code", "country_name", "ppp"]]
