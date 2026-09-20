# Stock schema migrations

Alembic begins with the seven tables declared in `app.models.stock`:
`stock`, `stock_quote_snapshot`, `stock_metric_snapshot`, `stock_daily_price`,
`stock_collection_state`, `stock_collection_job`, and `stock_data_coverage`.

The application already has tables created before Alembic was introduced. They
have no baseline revision in this directory. The initial revision is explicit
and creates only the seven stock tables; it does not create, alter, or drop
those existing tables. The Alembic environment uses a metadata subset for
these seven tables so schema comparison cannot propose removing unrelated
tables. Future revisions should keep that scope until a deliberate baseline is
introduced.

Run from `backend/` after the database is available:

```bash
uv run alembic upgrade head
```

Application startup and the market collector exclude the seven stock tables from
`create_all`; apply `uv run alembic upgrade head` before starting either process.
Use `uv run alembic check` to verify the managed schema. Existing non-stock tables
remain on the repository's prior initialization path.
