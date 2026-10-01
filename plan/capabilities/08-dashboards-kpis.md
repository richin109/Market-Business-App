# Capability 8: Dashboards & KPIs

- [ ] **Capability complete** (all features below checked)

Bounded context: `mbs/reporting/` dashboard layer (blueprint §8 Dashboard layer, §9.6). Pre-aggregated KPIs for operations and executive views, rendered as server-side Jinja2/HTMX pages with embedded charts.

## Feature 8.1 — ETL Dashboard Layer
- [ ] Feature complete
- [ ] `etl/dashboard/ops_kpis.py` equivalent: pre-aggregate Operations Dashboard KPIs (inventory status, reorder alerts, waste, spoilage).
- [ ] `etl/dashboard/exec_kpis.py` equivalent: pre-aggregate Executive Dashboard KPIs (weekly/monthly/YTD revenue, profit, margin).
- [ ] Both run only after Product Master and Inventory/Rankings layers succeed (Governance Rule 4 refresh sequence).
- [ ] Give every dashboard refresh a run ID, source-watermark timestamp, covered business-date range, status, and source-record counts. Publish Operations and Executive KPI snapshots atomically only when all required upstream inputs succeed; retain the prior published snapshot with a visible stale/failed status when a refresh is partial or fails.
- [ ] Before publishing ingredient inventory valuation, recipe-derived costs, or profit KPIs, treat unresolved D-56 historical provisional-input exceptions and unposted/unknown-date expiry movements as blocking upstream issues. Keep accepted Square revenue and its labelled provisional COGS available for authorized source review, not silently converted to recipe-derived profit; Health Score and issue lists remain diagnostic until evidence-backed resolution (PR-001; SL-004).
- [ ] Aggregate purchase, cost, and expense KPIs by canonical `store_id` and canonical `item_id`, so grouped store aliases and per-store descriptions roll up as one store and one item; show display names and common names for presentation only and keep drill-through to the underlying store item and printed description.
- [ ] Count receipt import activity by file/job separately from canonical orders and approved line occurrences. Dashboard cost, expense, stock, and profit aggregates consume only accepted business records, never copies or held OCR lines; drill-through retains the contributing receipt and source-file/page evidence without multiplying a purchase by its PDF count (RM-022).

## Feature 8.2 — Operations Dashboard
- [ ] Feature complete
- [ ] Page showing current inventory health, ingredients below reorder point (Capability 6.4), products needing setup/cost review (Capability 4), recent import activity (Capabilities 1–3).
- [ ] `GET /api/v1/dashboards/ops` (or equivalent) per blueprint §9.6.

## Feature 8.3 — Executive Dashboard
- [ ] Feature complete
- [ ] Weekly/monthly/YTD sales revenue from accepted Square sales, net of discounts and returns/refunds and excluding sales tax collected; show actual Square fees (estimates separately labeled), market fees, travel costs, approved operating expenses, and net operating profit; highlight weeks below `weekly_profit_goal` (default $300).
- [ ] Define net operating profit as sales revenue minus COGS, Square fees, market fees, travel costs, and approved operating expenses. Ingredient purchases update ingredient cost/on-hand inputs and must not also be expensed on top of COGS; sales tax collected is a liability, not revenue.
- [ ] Resolve every cost component of a weekly, monthly, or YTD figure as of the business date it belongs to, through the Capability 4.3 as-of-date rule and the Capability 6.3 lot cost, never from a single current cost applied across all periods (D-57). A reported week keeps its own cost answer when a later week's receipts change prices; a cost carried forward from an earlier week is labelled as such with its effective date, and an input with no cost on or before the period blocks only its own figure as an open D-25 issue. A late or backdated receipt recomputes an open period and produces a linked restatement for a closed one, with the restated and original values both reachable through drill-through (CS-001; CS-002).
- [ ] Include approved but unallocated expenses in business totals and surface their unallocated status; do not silently omit them from reporting.
- [ ] Market rankings and Opportunity Engine output surfaced here (Capability 7).
- [ ] `GET /api/v1/dashboards/exec` per blueprint §9.6.
- [ ] Show the refresh watermark/status and provide authorized drill-through from every displayed KPI to its refresh run and approved source records; never combine values from different refresh runs without an explicit partial-data warning.

## Feature 8.4 — Charting
- [ ] Feature complete
- [ ] Serve a version-pinned Chart.js or Plotly static asset locally in production; a CDN is permitted only for local prototyping. Apply the production content-security policy to chart assets and data endpoints.
- [ ] Chart data served as small JSON fragments from dedicated endpoints, refreshed via HTMX polling or on-demand refresh button.
- [ ] Test successful, failed, and partial upstream refreshes; prove a failed refresh cannot publish mixed-state KPIs, each displayed total traces to one refresh run and approved sources, and `Test Record = Yes` rows never appear.
