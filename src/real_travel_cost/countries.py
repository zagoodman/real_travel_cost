"""Country identity across sources: ISO-3 codes for IMF data, names for the State Dept."""

from __future__ import annotations

import pandas as pd

# The State Dept. feed publishes names only, so its rows are matched to ISO-3 by name.
ADVISORY_NAME_TO_CODE: dict[str, str] = {
    "Brunei": "BRN",
    "Burma": "MMR",
    "Burma (Myanmar)": "MMR",
    "Cabo Verde": "CPV",
    "Cote d Ivoire": "CIV",
    "Côte d'Ivoire": "CIV",
    "Egypt": "EGY",
    "Democratic Republic of the Congo": "COD",
    "Hong Kong": "HKG",
    "Iran": "IRN",
    "Israel, the West Bank and Gaza": "ISR",
    "Kosovo": "KSV",
    "Laos": "LAO",
    "Liechtenstein": "LIE",
    "Macau": "MAC",
    "Montserrat": "MSR",
    "Mexico Travel Advisory": "MEX",
    "North Korea": "PRK",
    "Republic of the Congo": "COG",
    "Russia": "RUS",
    "Saint Kitts and Nevis": "KNA",
    "Saint Lucia": "LCA",
    "Saint Vincent and the Grenadines": "VCT",
    "Sao Tome and Principe": "STP",
    "São Tomé and Príncipe": "STP",
    "Slovakia": "SVK",
    "Somalia": "SOM",
    "South Korea": "KOR",
    "Syria": "SYR",
    "Taiwan": "TWN",
    "The Bahamas": "BHS",
    "The Gambia": "GMB",
    "The Kyrgyz Republic": "KGZ",
    "Timor": "TLS",
    "Turkey": "TUR",
    "Turkiye": "TUR",
    "Türkiye": "TUR",
    "Venezuela": "VEN",
    "Vietnam": "VNM",
    "West Bank": "PSE",
    "Yemen": "YEM",
}

# The World Bank ships statistical-yearbook names ("Slovak Republic", "Egypt, Arab Rep.",
# "Viet Nam"). These are the current unabbreviated forms, keyed on ISO-3 so a relabelling
# upstream cannot silently reintroduce the old spelling. They are what the rankings display
# and what the advisory feed's names are matched against.
CANONICAL_NAMES: dict[str, str] = {
    "BHS": "The Bahamas",
    "BRN": "Brunei",
    "CIV": "Côte d'Ivoire",
    "COD": "Democratic Republic of the Congo",
    "COG": "Republic of the Congo",
    "CPV": "Cape Verde",
    "CUW": "Curaçao",
    "EGY": "Egypt",
    "FSM": "Micronesia",
    "GMB": "The Gambia",
    "HKG": "Hong Kong",
    "IRN": "Iran",
    "KGZ": "Kyrgyzstan",
    "KNA": "Saint Kitts and Nevis",
    "KOR": "South Korea",
    "LAO": "Laos",
    "LCA": "Saint Lucia",
    "MAC": "Macau",
    "MMR": "Myanmar",
    "NRU": "Nauru",
    "PRI": "Puerto Rico",
    "PSE": "Palestine",
    "RUS": "Russia",
    "SOM": "Somalia",
    "STP": "São Tomé and Príncipe",
    "SVK": "Slovakia",
    "SXM": "Sint Maarten",
    "SYR": "Syria",
    "TLS": "East Timor",
    "TUR": "Türkiye",
    "VCT": "Saint Vincent and the Grenadines",
    "VEN": "Venezuela",
    "VIR": "United States Virgin Islands",
    "VNM": "Vietnam",
    "YEM": "Yemen",
}


def canonicalize_names(frame: pd.DataFrame, name_column: str = "country_name") -> pd.DataFrame:
    """Replace upstream country labels with the current unabbreviated forms."""
    out = frame.copy()
    out[name_column] = out.country_code.map(CANONICAL_NAMES).fillna(out[name_column])
    return out


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
