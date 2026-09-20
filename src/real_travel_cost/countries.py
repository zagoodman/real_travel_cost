"""Country identity across sources: ISO-3 codes for IMF data, names for the State Dept."""

from __future__ import annotations

import pandas as pd

# One entry per country, keyed on ISO-3: the display name first, then every spelling the
# State Dept. feed has used for it. Both lookups below derive from this, so a new feed
# spelling is one line here rather than an edit in two places that can drift apart.
#
# Only countries needing an override appear; the rest display the World Bank's own label.
COUNTRY_NAMES: dict[str, tuple[str, ...]] = {
    "ARE": ("United Arab Emirates", "United Arab Emirates (UAE)"),
    "BHS": ("The Bahamas", "Bahamas"),
    "BIH": ("Bosnia and Herzegovina", "Bosnia-Herzegovina"),
    "BRN": ("Brunei",),
    "CAF": ("Central African Republic", "Central African Republic (CAR)"),
    "CHN": ("China", "Mainland China, Hong Kong & Macau"),
    "CIV": ("Côte d'Ivoire", "Cote d Ivoire", "Cote d'Ivoire", "Côte d'Ivoire (Ivory-Coast)"),
    "COD": (
        "Democratic Republic of the Congo",
        "Congo-Kinshasha (DRC)",
        "Democratic Republic of the Congo (D.R.C.)",
    ),
    "COG": ("Republic of the Congo", "Congo-Brazzaville (ROC)"),
    "CPV": ("Cape Verde", "Cabo Verde"),
    "CUW": ("Curaçao", "Curacao"),
    "CZE": ("Czechia", "Czech Republic"),
    "DNK": ("Denmark", "Kingdom of Denmark"),
    "DOM": ("Dominican Republic", "Domincan Republic"),
    "EGY": ("Egypt",),
    "FRA": ("France", "France (includes Monaco)", "France *Monaco"),
    "FSM": ("Micronesia",),
    "GBR": ("United Kingdom", "United Kingdom of Great Britain and Northern Ireland"),
    "GMB": ("The Gambia",),
    "HKG": ("Hong Kong",),
    "HND": ("Honduras", "Houduras"),
    "IRN": ("Iran",),
    "ISR": (
        "Israel",
        "Israel, the West Bank and Gaza",
        "Israel, The West Bank and Gaza",
        "Israel, The West Bank, and Gaza",
    ),
    "KGZ": ("Kyrgyzstan", "The Kyrgyz Republic"),
    "KNA": ("Saint Kitts and Nevis",),
    "KOR": ("South Korea",),
    "KSV": ("Kosovo",),
    "LAO": ("Laos",),
    "LCA": ("Saint Lucia",),
    "LIE": ("Liechtenstein", "Liechtenstien"),
    "MAC": ("Macau",),
    "MEX": ("Mexico", "Mexico Travel Advisory"),
    "MKD": ("North Macedonia", "Macedonia", "Republic of North Macedonia"),
    "MMR": ("Myanmar", "Burma", "Burma (Myanmar)"),
    "MSR": ("Montserrat",),
    "NRU": ("Nauru",),
    "PHL": ("Philippines", "Phillippines"),
    "PRI": ("Puerto Rico",),
    "PRK": ("North Korea", "North Korea (Democratic People's Republic of Korea)"),
    "PSE": ("Palestine", "West Bank"),
    "RUS": ("Russia",),
    "SLB": ("Solomon Islands", "Solomon Island"),
    "SOM": ("Somalia",),
    "STP": ("São Tomé and Príncipe", "Sao Tome and Principe", "Sao Tome & Principe"),
    "SVK": ("Slovakia",),
    "SWZ": ("Eswatini", "Eswatini (Swaziland)", "Swaziland"),
    "SXM": ("Sint Maarten",),
    "SYR": ("Syria",),
    "TCA": ("Turks and Caicos Islands", "Turks and Caicos"),
    "TLS": ("East Timor", "Timor", "Timor-Leste"),
    "TUR": ("Türkiye", "Turkey", "Turkiye"),
    "TWN": ("Taiwan",),
    "VCT": ("Saint Vincent and the Grenadines", "Saint Vincent and The Grenadines"),
    "VEN": ("Venezuela",),
    "VIR": ("United States Virgin Islands",),
    "VNM": ("Vietnam",),
    "YEM": ("Yemen",),
}

# Derived: ISO-3 -> display name. Keyed on code so an upstream relabelling cannot quietly
# reintroduce an old spelling.
CANONICAL_NAMES: dict[str, str] = {code: names[0] for code, names in COUNTRY_NAMES.items()}

# Derived: every known spelling -> ISO-3. The feed is name-only, so this is the lookup
# direction that matters; it is many-to-one because State renames destinations over time.
ADVISORY_NAME_TO_CODE: dict[str, str] = {
    name: code for code, names in COUNTRY_NAMES.items() for name in names
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
