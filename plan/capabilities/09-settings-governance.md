# Capability 9: Settings & Governance

- [ ] **Capability complete** (all features below checked)

Bounded context: `mbs/governance/` + `tbl_settings` (blueprint §7, §12). Configuration store and the non-negotiable rules enforced at the application layer.

## Feature 9.1 — Settings Store
- [ ] Feature complete
- [ ] `tbl_settings` key-value table with the full settings catalog from blueprint §7: `mileage_rate` ($0.67), `market_ranking_min_visits` (5), `week_starts_on` (Monday), `testing_mode` (No), `weekly_profit_goal` ($300.00), `safety_stock_pct` (20%), `cost_review_threshold_days` (90), `square_fee_rate` (2.6%), `square_fee_fixed_amount` ($0.10), `nonperishable_low_stock_threshold_pct` (20%), plus `ocr_engine` (from Capability 1).
- [ ] Keep effective-dated history for `mileage_rate`, `square_fee_rate`, and `square_fee_fixed_amount`; apply the schedule effective on the transaction/market date so a current setting change cannot rewrite historical profit. The reorder engine uses the explicit ingredient-level Safety Stock Quantity in the workbook. Retain `safety_stock_pct` only for source-workbook compatibility; it has no calculation effect until an owner-approved conversion is specified.
- [ ] Settings API (read for VIEWER+, write for ADMIN) — changes apply immediately, no service restart.
- [ ] Changing a non-historical calculation setting (safety stock default, cost threshold) re-derives affected current outputs; effective-dated rates apply prospectively and do not rewrite historical results.

## Feature 9.2 — Governance Rule Enforcement
- [ ] Feature complete
- [ ] Rule 1 — Product Key Rule: Variation ID only, enforced at the model/service layer, not just UI.
- [ ] Rule 2 — Market Master Immutability: enforced via service layer that blocks UPDATE on historical rows, only allows end-date + insert.
- [ ] Rule 3 — Test Record Isolation: isolate fixtures in test-only databases where practical and enforce production query filters excluding `Test Record = Yes` from every aggregation/dashboard/report; add tests proving test rows cannot leak into production results.
- [ ] Rule 4 — Required Refresh Sequence: for MVP 2, Catalog → minimum product/cost readiness and market/location/dated-visit setup → Orders/Payments → inventory/COGS/rankings → dashboards → testing. Block Orders acceptance until its preflight passes; later approved purchase, expense, market, and production changes trigger downstream recalculation in dependency order.
- [ ] Rule 4 — Required Refresh Sequence: Catalog sync → per-line product/cost and market/location/dated-visit readiness → accept passing Orders lines and stage exceptions → downstream inventory/COGS/rankings → dashboards → testing. A failing line does not block other passing lines; later approved purchase, expense, market, and production changes trigger downstream recalculation in dependency order.
- [ ] Rule 5 — Deduplication: upsert Square order lines by stable Square Order ID + Line Item UID; deduplicate receipts by the Receipt_ID composite key; make both paths replay-safe and auditable.
- [ ] Rule 7 — Cost Review: flags per Capability 4.4.
- [ ] Rule 8 — Spoilage Logic: enforced per Capability 6.2.

## Feature 9.3 — Error Logging
- [ ] Feature complete
- [ ] Central error log table capturing ETL/import/governance rule violations with severity, timestamp, and source module — feeds the Release Gate (Capability 10).
