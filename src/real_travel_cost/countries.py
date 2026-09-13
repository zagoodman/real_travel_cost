"""Country identity across sources: ISO-3 codes for IMF data, names for the State Dept."""

from __future__ import annotations

import pandas as pd

# The State Dept. feed publishes names only, so its rows are matched to ISO-3 by name.
ADVISORY_NAME_TO_CODE: dict[str, str] = {
    "Burma (Myanmar)": "MMR",
    "Cote d Ivoire": "CIV",
    "Democratic Republic of the Congo": "COD",
    "Hong Kong": "HKG",
    "Iran": "IRN",
    "Israel, the West Bank and Gaza": "ISR",
    "Kosovo": "KSV",
    "Laos": "LAO",
    "Macau": "MAC",
    "Republic of the Congo": "COG",
    "Russia": "RUS",
    "South Korea": "KOR",
    "Syria": "SYR",
    "Taiwan": "TWN",
    "The Bahamas": "BHS",
    "The Gambia": "GMB",
    "Turkiye": "TUR",
    "Türkiye": "TUR",
    "Venezuela": "VEN",
    "Vietnam": "VNM",
}

# Countries whose PPP factor predates a currency switch, so it is quoted in the old unit.
# Value is the last month the old currency applied; rows at or after it are dropped.
REDENOMINATED: dict[str, str] = {"HRV": "2023-01-01"}  # kuna -> euro

# Countries with no own-currency IMF series -> the code whose rate they borrow.
SHARED_CURRENCIES: dict[str, list[str]] = {
    "G163": [  # euro area
        "AUT",
        "BEL",
        "CYP",
        "EST",
        "FIN",
        "FRA",
        "DEU",
        "GRC",
        "HRV",
        "IRL",
        "ITA",
        "LVA",
        "LTU",
        "LUX",
        "MLT",
        "MCO",
        "NLD",
        "PRT",
        "SVK",
        "SVN",
        "ESP",
    ],
    "DNK": ["GRL", "FRO"],
}


def attach_country_codes(
    advisories: pd.DataFrame, reference: pd.DataFrame, name_column: str = "country_name"
) -> pd.DataFrame:
    """Add `country_code` to name-keyed rows, by explicit mapping then exact name match."""
    lookup = dict(zip(reference[name_column], reference.country_code, strict=False))
    out = advisories.copy()
    out["country_code"] = (
        out[name_column].map(ADVISORY_NAME_TO_CODE).fillna(out[name_column].map(lookup))
    )
    return out


def unmatched(frame: pd.DataFrame, name_column: str = "country_name") -> pd.Series:
    """Names that got no ISO-3 code; drives ADVISORY_NAME_TO_CODE maintenance."""
    return frame.loc[frame.country_code.isnull(), name_column].sort_values().reset_index(drop=True)
