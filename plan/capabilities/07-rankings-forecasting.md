# Capability 7: Rankings & Forecasting

- [ ] **Capability complete** (all features below checked)

Bounded contexts: `mbs/reporting/` + `mbs/forecasting/` (blueprint §3.1 #6/#8, Modules 11–14). Product scorecards, market rankings, opportunity engine, and rolling forecasts.

## Feature 7.1 — Product Scorecards
- [ ] Feature complete
- [ ] Per-product metrics across configurable date ranges (Module 11): Revenue, COGS, Profit, Margin %, Units Sold, Waste Units, Waste % (`Waste Units / (Units Sold + Waste Units)`), Growth % vs. prior period, Lifecycle Status.
- [ ] Match workbook lifecycle thresholds: Growing at growth >= 20%; Declining at growth <= -20%; otherwise New when Units Sold < 10, else Stable. Define zero/negative revenue and missing-period behavior in tests.
- [ ] `tblProductRankings` equivalent storing computed scorecard snapshots for fast dashboard reads.

## Feature 7.2 — Market Rankings
- [ ] Feature complete
- [ ] Rank markets by business and personal scores once a market reaches `market_ranking_min_visits` (default 5) — markets below threshold show as **Unranked** (Module 12).
- [ ] Preserve independent business and personal ranks. Deterministic tie-break order: score descending, lifetime average profit descending, visit count descending, then market name ascending; exclude test records.
- [ ] Ranking confidence is Insufficient Data below the visit threshold, Medium from the threshold through 9 visits, and High at 10+ visits; expose eligibility, confidence, and ranking reason.
- [ ] `tblMarketRankings` equivalent, recomputed on each Dashboard-layer ETL refresh.

## Feature 7.3 — Market Opportunity Engine
- [ ] Feature complete
- [ ] Capture manager-reviewed Revenue Growth, Profit Growth, Visit Frequency, and Reliability component scores for each market as-of date; each input is a numeric 0–100 score with reviewer/source note. These are source-workbook inputs, not formulas derived from the underlying metrics; do not invent a scoring algorithm.
- [ ] Match workbook weights: Revenue Growth 30%, Profit Growth 35%, Visit Frequency 15%, Reliability 20%; tiers are High at >=80, Medium at >=60, otherwise Low. Preserve the corresponding action (Increase Attendance, Monitor, Review).
- [ ] Calculate `Opportunity Score = Revenue Growth Score × 0.30 + Profit Growth Score × 0.35 + Visit Frequency Score × 0.15 + Reliability Score × 0.20`; clamp/validate inputs to 0–100; tiers are High at >=80, Medium at >=60, otherwise Low. Preserve the corresponding action (Increase Attendance, Monitor, Review).
- [ ] Surface top/bottom opportunity markets on the Executive Dashboard (Capability 8).

## Feature 7.4 — Forecasting
- [ ] Feature complete
- [ ] Rolling averages at 4-week, 8-week, 13-week windows (Module 14).
- [ ] Match workbook forecast: Next Week = ROUND(4-week average × 0.50 + 8-week average × 0.30 + 13-week average × 0.20, 2); Next Month = Next Week × 4.345.
- [ ] Confidence compares 4-week and 13-week averages using `ABS(4-week - 13-week) / MAX(1, 13-week)`: High at <=10%, Medium at <=25%, otherwise Low. Define behavior for insufficient history and negative values.
- [ ] Outputs: Next Week Forecast, Next Month Forecast, Confidence Level.
- [ ] Exclude any `Test Record = Yes` rows from all forecast inputs (Governance Rule 3).
