# Local D1 replica for development. Nothing here touches the remote database except db-push.
DB   := real-travel-cost
LOCAL := db/local.sqlite

.PHONY: local seed publish push pull reset
## Build a complete local replica from scratch (no D1 access needed).
local: reset seed publish
	@sqlite3 $(LOCAL) "select 'panel', count(*) from panel union all select 'obs', count(*) from advisory_observations;"

reset:
	rm -f $(LOCAL)
	sqlite3 $(LOCAL) < db/schema.sql

seed:
	uv run python scripts/seed_advisory_history.py
	sqlite3 $(LOCAL) < db/seed_advisory_observations.sql

publish:
	uv run python scripts/publish_d1.py
	sqlite3 $(LOCAL) < db/publish.sql

## Apply the same SQL to the real D1 database.
push:
	wrangler d1 execute $(DB) --remote --file db/publish.sql

## Overwrite the local replica with production data.
pull:
	wrangler d1 export $(DB) --remote --output db/remote-dump.sql
	rm -f $(LOCAL) && sqlite3 $(LOCAL) < db/remote-dump.sql
