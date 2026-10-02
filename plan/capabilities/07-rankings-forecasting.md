# Capability 7: Rankings & Forecasting

Database: PostgreSQL only; see [D-77](../00-overview.md#postgresql-contract-all-stages).
- [ ] Test tie/as-of boundaries, full-date history, NULL/blocked vs zero, and publication from one refresh version without mixed snapshots.

- [ ] **Capability complete** (all features below checked)

Bounded contexts: `mbs/reporting/`, `mbs/forecasting/` (blueprint §3.1 #6/#8, Modules 11–14). Owns scorecards, rankings, opportunity, rolling forecasts.

## Feature 7.1 — Product Scorecards
- [ ] Feature complete
- [ ] Per-product metrics by configurable period: revenue, COGS, profit, margin, units sold, waste units/percent (`waste/(sold+waste)`), growth vs prior period, lifecycle (Module 11).
- [ ] Match workbook lifecycle thresholds: Growing at growth >= 20%; Declining at growth <= -20%; otherwise New when Units Sold < 10, else Stable. If either comparison-period revenue is zero or negative, or either period is missing, set growth to `NOT_COMPARABLE`, suppress Growing/Declining classification, and surface the scorecard for review rather than treating the value as zero.
- [ ] `tblProductRankings` equivalent storing computed scorecard snapshots for fast dashboard reads.

## Feature 7.2 — Market Rankings
- [ ] Feature complete
- [ ] Rank business/personal scores only at `market_ranking_min_visits` (default 5); below threshold show **Unranked** (Module 12).
- [ ] Preserve independent business and personal ranks. Deterministic tie-break order: score descending, lifetime average profit descending, visit count descending, then market name ascending; exclude test records.
- [ ] Ranking confidence is Insufficient Data below the visit threshold, Medium from the threshold through 9 visits, and High at 10+ visits; expose eligibility, confidence, and ranking reason.
- [ ] `tblMarketRankings` equivalent, recomputed on each Dashboard-layer ETL refresh.

## Feature 7.3 — Market Opportunity Engine
- [ ] Feature complete
- [ ] Capture manager-reviewed 0–100 Revenue Growth, Profit Growth, Visit Frequency, Reliability scores per market with actor/time/note/history. Last entered Business/Personal score stays active until replaced. These are workbook inputs; do not derive/invent scores.
- [ ] Calculate `Opportunity Score = Revenue Growth Score × 0.30 + Profit Growth Score × 0.35 + Visit Frequency Score × 0.15 + Reliability Score × 0.20`; clamp/validate inputs to 0–100; tiers are High at >=80, Medium at >=60, otherwise Low. Preserve the corresponding action (Increase Attendance, Monitor, Review).
- [ ] Surface top/bottom opportunity markets on the Executive Dashboard (Capability 8).

## Feature 7.4 — Forecasting
- [ ] Feature complete
- [ ] Calculate 4/8/13-week rolling averages (Module 14). Require 13 completed weeks with nonnegative net sales; otherwise show `INSUFFICIENT_HISTORY` or `REVIEW_NEGATIVE_HISTORY`, never zero.
- [ ] Match workbook forecast: Next Week = ROUND(4-week average × 0.50 + 8-week average × 0.30 + 13-week average × 0.20, 2); Next Month = Next Week × 4.345.
- [ ] Confidence compares 4-week and 13-week averages using `ABS(4-week - 13-week) / MAX(1, 13-week)`: High at <=10%, Medium at <=25%, otherwise Low. Forecasts without the required history or with negative history have no confidence level and remain review exceptions.
- [ ] Test missing periods, zero revenue, returns-only/negative periods, exactly 4/8/13 completed weeks, threshold boundaries, and null-versus-zero display behavior for every lifecycle, ranking-confidence, and forecast output.
- [ ] Outputs: Next Week Forecast, Next Month Forecast, Confidence Level.
- [ ] Exclude any `Test Record = Yes` rows from all forecast inputs (Governance Rule 3).
