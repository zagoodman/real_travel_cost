-- D1 schema. Every table keys on ISO-3; names are display-only and live in `countries`.
-- Apply with: wrangler d1 execute real-travel-cost --file db/schema.sql [--local|--remote]

-- Code -> display name. Materializes CANONICAL_NAMES over the World Bank's labels, so the
-- dashboard needs no name table of its own and no World Bank fetch.
CREATE TABLE IF NOT EXISTS countries (
  country_code TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  source       TEXT NOT NULL CHECK (source IN ('canonical', 'worldbank'))
);

-- Append-only. One row per country-month; never revised, so a rerun is a no-op and a bad
-- run can only fail to extend history, not corrupt it.
CREATE TABLE IF NOT EXISTS advisory_observations (
  country_code TEXT NOT NULL,
  month        TEXT NOT NULL,  -- YYYY-MM-01
  level        INTEGER NOT NULL CHECK (level BETWEEN 1 AND 4),
  issued       TEXT,           -- date State stamped on the advisory (RSS pubDate)
  observed_at  TEXT,           -- UTC read time; under OR IGNORE this is the FIRST sighting,
                               -- so a rerun in the same month keeps the original timestamp
  source       TEXT NOT NULL CHECK (source IN ('wayback', 'rss')),
  PRIMARY KEY (country_code, month)
);

CREATE INDEX IF NOT EXISTS advisory_observations_month ON advisory_observations (month);

-- Replaced wholesale each build: the anchor year moving forward rewrites every historical
-- value, so this cannot be appended to.
CREATE TABLE IF NOT EXISTS panel (
  country_code        TEXT NOT NULL,
  date                TEXT NOT NULL,  -- YYYY-MM-01
  advisory_level      INTEGER,
  current_dollars     REAL,
  price_level_nowcast REAL,
  cpi                 REAL,
  exr                 REAL,
  relative_prices     REAL,
  PRIMARY KEY (country_code, date)
);

CREATE INDEX IF NOT EXISTS panel_date ON panel (date);

-- One row per build. Lets the dashboard show data vintage and makes a stalled job visible.
CREATE TABLE IF NOT EXISTS build_meta (
  built_at       TEXT PRIMARY KEY,  -- ISO-8601 UTC
  anchor_year    INTEGER,
  panel_rows     INTEGER,
  countries      INTEGER,
  latest_month   TEXT,
  git_sha        TEXT,
  -- The feed regenerates continuously; these identify which upstream build a run saw.
  feed_last_modified TEXT,
  feed_bytes         INTEGER,
  feed_reads         INTEGER
);
