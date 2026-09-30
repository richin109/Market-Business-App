# Capability 8: Dashboards & KPIs

- [ ] **Capability complete** (all features below checked)

Bounded context: `mbs/reporting/` dashboard layer (blueprint §8 Dashboard layer, §9.6). Pre-aggregated KPIs for operations and executive views, rendered as server-side Jinja2/HTMX pages with embedded charts.

## Feature 8.1 — ETL Dashboard Layer
- [ ] Feature complete
- [ ] `etl/dashboard/ops_kpis.py` equivalent: pre-aggregate Operations Dashboard KPIs (inventory status, reorder alerts, waste, spoilage).
- [ ] `etl/dashboard/exec_kpis.py` equivalent: pre-aggregate Executive Dashboard KPIs (weekly/monthly/YTD revenue, profit, margin).
- [ ] Both run only after Product Master and Inventory/Rankings layers succeed (Governance Rule 4 refresh sequence).

## Feature 8.2 — Operations Dashboard
- [ ] Feature complete
- [ ] Page showing current inventory health, ingredients below reorder point (Capability 6.4), products needing setup/cost review (Capability 4), recent import activity (Capabilities 1–3).
- [ ] `GET /api/v1/dashboards/ops` (or equivalent) per blueprint §9.6.

## Feature 8.3 — Executive Dashboard
- [ ] Feature complete
- [ ] Weekly/monthly/YTD sales revenue from accepted Square and manual sales, net of discounts and returns/refunds and excluding sales tax collected; show actual Square fees (estimates separately labeled), market fees, travel costs, approved operating expenses, and net operating profit; highlight weeks below `weekly_profit_goal` (default $300).
- [ ] Define net operating profit as sales revenue minus COGS, Square fees, market fees, travel costs, and approved operating expenses. Ingredient purchases update ingredient cost/on-hand inputs and must not also be expensed on top of COGS; sales tax collected is a liability, not revenue.
- [ ] Include approved but unallocated expenses in business totals and surface their unallocated status; do not silently omit them from reporting.
- [ ] Market rankings and Opportunity Engine output surfaced here (Capability 7).
- [ ] `GET /api/v1/dashboards/exec` per blueprint §9.6.

## Feature 8.4 — Charting
- [ ] Feature complete
- [ ] Embed Chart.js (or Plotly) via CDN `<script>` tag directly in Jinja2 templates — no npm/webpack build step.
- [ ] Chart data served as small JSON fragments from dedicated endpoints, refreshed via HTMX polling or on-demand refresh button.
