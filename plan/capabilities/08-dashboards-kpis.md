# Capability 8: Dashboards & KPIs

Database: PostgreSQL only; see [D-77](../00-overview.md#postgresql-contract-all-stages).
- [ ] Test aggregation precision, source/test filters, incomplete totals, stable order, and KPI drill-through to one published refresh.

- [ ] **Capability complete** (all features below checked)

Bounded context: `mbs/reporting/` (blueprint §8, §9.6). Pre-aggregate Operations/Executive KPIs; render server-side Jinja2/HTMX with embedded charts.

## Feature 8.1 — ETL Dashboard Layer
- [ ] Feature complete
- [ ] `etl/dashboard/ops_kpis.py` equivalent: pre-aggregate Operations Dashboard KPIs (inventory status, reorder alerts, waste, spoilage).
- [ ] `etl/dashboard/exec_kpis.py` equivalent: pre-aggregate Executive Dashboard KPIs (weekly/monthly/YTD revenue, profit, margin).
- [ ] Both run only after Product Master and Inventory/Rankings layers succeed (Governance Rule 4 refresh sequence).
- [ ] Record refresh ID, source watermark, business-date range, status, and source counts. Atomically publish both KPI snapshots only after all required inputs succeed; on partial/failure retain prior snapshot and show stale/failed.
- [ ] Before publishing ingredient inventory valuation, recipe-derived costs, or profit KPIs, consume the D-61 typed blocked results returned by the cost, valuation, and balance services rather than re-deriving independent checks; treat unresolved D-56 contingency exceptions and unposted/unknown-date expiry movements as blocking upstream issues. Publish an aggregate containing a blocked component as incomplete with its blocking list attached, never as a silently reduced total. Keep accepted Square revenue and any labelled contingency COGS available for authorized source review, not silently converted to recipe-derived profit; Health Score and issue lists read the same register and remain diagnostic until evidence-backed resolution (SL-004).
- [ ] Aggregate purchases/costs/expenses by canonical `store_id`/`item_id`; aliases and descriptions roll up accordingly. Names are display-only; drill through to store item and printed description.
- [ ] Separate file/job counts from canonical orders/approved occurrences. Aggregate only accepted records, never copies/held OCR; drill through receipt/source/page without multiplying by PDF count (RM-022).

## Feature 8.2 — Operations Dashboard
- [ ] Feature complete
- [ ] Show inventory health, below-reorder ingredients (Cap 6.4), setup/cost-review products (Cap 4), recent imports (Caps 1–3).
- [ ] `GET /api/v1/dashboards/ops` (or equivalent) per blueprint §9.6.

## Feature 8.3 — Executive Dashboard
- [ ] Feature complete
- [ ] Show accepted Square weekly/monthly/YTD revenue net of discounts/refunds and excluding sales tax; actual fees (estimates labeled), market/travel fees, approved expenses, net operating profit; flag weeks below `weekly_profit_goal` (default $300).
- [ ] Define net operating profit as sales revenue minus COGS, Square fees, market fees, travel costs, and approved operating expenses. Ingredient purchases update ingredient cost/on-hand inputs and must not also be expensed on top of COGS; sales tax collected is a liability, not revenue.
- [ ] Resolve each cost by its period date using Cap 4.3/6.3, never one current cost (D-57). Later prices cannot alter prior weeks; label carry-forward date; block only figures missing prior cost as D-25 issues. Late receipts recompute open periods or append closed-period restatements; retain original/restated drill-through (CS-001/002).
- [ ] Include approved but unallocated expenses in business totals and surface their unallocated status; do not silently omit them from reporting.
- [ ] Market rankings and Opportunity Engine output surfaced here (Capability 7).
- [ ] `GET /api/v1/dashboards/exec` per blueprint §9.6.
- [ ] Show refresh watermark/status; link each KPI to run and approved sources. Never mix refresh runs without a partial-data warning.

## Feature 8.4 — Charting
- [ ] Feature complete
- [ ] Serve a version-pinned Chart.js or Plotly static asset locally in production; a CDN is permitted only for local prototyping. Apply the production content-security policy to chart assets and data endpoints.
- [ ] Chart data served as small JSON fragments from dedicated endpoints, refreshed via HTMX polling or on-demand refresh button.
- [ ] Test successful, failed, and partial upstream refreshes; prove a failed refresh cannot publish mixed-state KPIs, each displayed total traces to one refresh run and approved sources, and `Test Record = Yes` rows never appear.
