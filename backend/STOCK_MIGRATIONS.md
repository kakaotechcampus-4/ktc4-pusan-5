# Stock schema migrations

Alembic begins with the seven tables declared in `app.models.stock`:
`stock`, `stock_quote_snapshot`, `stock_metric_snapshot`, `stock_daily_price`,
`stock_collection_state`, `stock_collection_job`, and `stock_data_coverage`.

Revision `20260920_02` adds `stock_annual_income` and `stock_annual_eps` for
annual financial trends and expands the job resource check to permit `income`
and `eps`. It is additive and leaves existing rows untouched on upgrade. A
downgrade removes those tables and explicitly deletes their income and EPS job
and state rows before restoring the original resource check.

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

Revision `20260920_03` adds nullable `roe` and `debt_ratio` columns to annual
EPS, adds `stock_annual_stability`, and permits `stability` jobs. Upgrade keeps
existing EPS rows but clears their `last_success_at` so the new fields are
fetched without waiting for the normal TTL. Downgrade removes stability
jobs/state, the stability table, and the two EPS health columns.

Revision `20260920_04` adds quarterly YTD income and ratio tables and permits
`quarter_income` and `quarter_ratios` jobs. Quarterly income retains the
provider's `fiscal_year_end_month` so non-December fiscal calendars are not
mistakenly converted into ordinary calendar quarters. Downgrade removes those
quarterly jobs/state rows and both tables.

Revision `20260920_05` adds `stock_period_market` for historical market cap and
relative strength values, plus `krx_historical_cache`, a shared market/date
response cache for KRX stock and index requests. It permits `history_cap` and
`history_rs` jobs and removes those jobs/state rows on downgrade.
