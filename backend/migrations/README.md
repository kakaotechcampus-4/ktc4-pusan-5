# Alembic migrations

This migration directory starts at the stock schema only. Existing tables were
created before Alembic was introduced and intentionally have no baseline
revision here. The first revision therefore creates only the seven tables from
`app.models.stock`; it does not inspect, create, alter, or drop the existing
application tables.

The environment exposes a metadata subset containing only those seven stock
tables for safe schema inspection. The initial migration itself is explicit and
does not rely on autogenerate. Future revisions must keep the pre-Alembic
tables outside their managed scope until a deliberate baseline is added.

Run from `backend/` after the database is available:

```bash
alembic upgrade head
```

The application currently calls `Base.metadata.create_all` during startup and
the market collector does the same. Do not run this migration against an
application process that has imported the stock models until that startup
behavior has been disabled or otherwise coordinated; use one schema creation
path at a time.
