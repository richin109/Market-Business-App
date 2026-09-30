# Capability 12: Tax Information & Filing Support

- [ ] **Capability complete** (all features below checked)

Bounded context: `mbs/tax_reporting/`. Produces year-specific, reviewable business-tax workpapers and source-linked exports for the owner or tax professional. This capability supports preparation; it does not determine legal tax treatment, calculate a final tax liability, prepare the owner's complete personal return, or transmit/file returns.

## Feature 12.1 — Tax Profile & Applicability
- [ ] Feature complete
- [ ] Set the current federal profile to sole proprietorship, reported as part of the owner's Form 1040; target Schedule C (Form 1040) workpapers by default. Keep entity type/tax classification editable with an audit trail if the business structure or election changes.
- [ ] Capture tax year/accounting period, federal accounting method, business start/end dates, ownership details, tax preparer, and applicable operating jurisdictions.
- [ ] Capture Florida Department of Revenue account types and filing frequencies when applicable: sales and use tax, corporate income/franchise tax, and reemployment tax if there are employees. Keep state/local account identifiers encrypted and access-controlled; do not expose them in routine exports or logs.
- [ ] Use the confirmed sole-proprietor/Schedule C path unless the saved tax profile is changed; do not infer a different federal tax classification from the business name or Florida legal entity alone.
- [ ] Florida has no individual income tax return; do not generate a Florida individual income-tax form. Clearly show state business filing tasks only when the selected entity/activity makes them applicable.
- [ ] Keep applicability and form mappings configurable by tax year and link to current official IRS/Florida DOR instructions; never hard-code tax rates, thresholds, or eligibility rules as timeless constants.

## Feature 12.2 — Federal Business Tax Workpapers
- [ ] Feature complete
- [ ] Generate a tax-year Schedule C-aligned workpaper (current IRS line mapping) with gross receipts, returns/allowances, COGS support, gross profit, expenses, vehicle/mileage evidence, other expenses, and net profit, plus source-linked detail schedules. Label it clearly as a preparation workpaper, not an official IRS return.
- [ ] Export a printable PDF and supporting XLSX/CSV schedules for the owner or preparer to use with Form 1040 filing software or a tax professional; do not generate/sign/file Form 1040 or transmit the workpaper as a return.
- [ ] Prepare annual gross-receipts reconciliation from accepted Square Orders and audited manual cash/other non-Square sales, refunds/returns, discounts, and payment-settlement reports. Reconcile Forms 1099-K and other third-party statements to the underlying sales; identify sales tax collected, Square fees, refunds, timing differences, and deposits separately so gross receipts are not confused with net payouts. Missing source coverage remains a blocking close exception.
- [ ] Produce an inventory/COGS support schedule with beginning and ending quantities/values, purchases net of returns/allowances, personal withdrawals, production materials, labor/other cost inputs where recorded, valuation method, and a reconciliation to operational inventory. Flag unsupported tax/accounting choices for review rather than choosing a method.
- [ ] Summarize operating expenses by user-/preparer-reviewed tax category and period; identify personal, mixed-use, missing-receipt, unallocated, and potentially nondeductible items for review. Do not treat the app's management-profit categories as tax classifications automatically.
- [ ] Include the capital-asset register, acquisitions/disposals, purchase cost, business-use percentage, placed-in-service/disposal dates, and prior/current depreciation data supplied by the preparer. Provide a depreciation workpaper/export; do not automatically elect Section 179, bonus depreciation, or a depreciation method.
- [ ] Provide business vehicle and mileage evidence: date, vehicle, starting/ending locations, business purpose, route legs, business miles, personal/commuting miles where known, and parking/tolls. Support travel outside market routes and mark incomplete logs; do not assume all Home-to-market travel is deductible.
- [ ] Include year-to-date estimated tax payments/withholding entered or imported by the user, and optional payroll and contractor-payment summaries. Keep payee tax IDs and source tax forms encrypted and out of general-purpose exports unless explicitly selected for an authorized tax package.
- [ ] Make clear that the Schedule C package is business-only. Owner wages, spouse income, personal deductions/credits, other businesses, and other Form 1040 inputs remain outside the app and must be supplied separately to the owner's tax software or preparer.
- [ ] Provide a Schedule SE support summary for business net profit and source records where useful, but do not calculate final self-employment tax because the owner's other income and individual circumstances are outside this business system.

## Feature 12.3 — Florida State & Local Business Tax Workpapers
- [ ] Feature complete
- [ ] Provide a Florida sales/use tax workpaper by filing period, market/location, and tax code: gross sales, taxable sales, exempt sales and reason, returns/refunds, discounts, state tax, county discretionary surtax, tax collected, tax due/paid, and adjustments.
- [ ] Store product/transaction taxability and exemption codes as user-/preparer-reviewed, effective-dated mappings. Do not infer food/product taxability from OCR merchandise categories or hard-code rates; Florida taxability, surtax, and location rules can vary by transaction and change over time.
- [ ] Reconcile Square-collected sales tax to the sales ledger, filed Florida returns, and payment confirmations; identify missing tax codes, location/jurisdiction uncertainty, over/under-collection, and unfiled periods.
- [ ] Track possible use-tax purchases where sales tax was not charged, with receipt, vendor, purchase location, intended use, and review status; do not calculate or post use tax without an approved rule.
- [ ] Where applicable, prepare source summaries for Florida corporate income/franchise filings and reemployment tax using entity and payroll records. Show these as conditional obligations, not universal filings.
- [ ] Link to official Florida DOR guidance and current-year forms, including [Sales and Use Tax](https://floridarevenue.com/taxes/taxesfees/Pages/sales_tax.aspx), [Corporate Income Tax](https://floridarevenue.com/taxes/taxesfees/Pages/corporate.aspx), [Reemployment Tax](https://floridarevenue.com/taxes/taxesfees/Pages/reemployment.aspx), and the [tax forms index](https://floridarevenue.com/Pages/forms_index.aspx).

## Feature 12.4 — Review, Reconciliation & Export
- [ ] Feature complete
- [ ] Create a tax-year close checklist for missing receipts, unreviewed OCR items, unmatched 1099-K amounts, unresolved refunds, inventory counts/valuation, uncategorized expenses, asset disposals, mileage gaps, sales-tax exceptions, and tax payments.
- [ ] Preserve drill-through from every workpaper total to source Square order/payment, receipt line, purchase, expense, market visit, inventory record, asset, imported form, or manual adjustment.
- [ ] Generate a versioned tax-year snapshot and export workbook/CSV schedules plus a source-document index for an authorized owner or preparer. Record who generated/reviewed the package, included records, unresolved exceptions, and export timestamp.
- [ ] Allow corrections through auditable adjustments and generate a new snapshot; never silently rewrite a previously exported or reviewed tax package.
- [ ] Require owner/preparer confirmation of tax classifications and filing decisions. No direct IRS/Florida e-filing, return signatures, tax-payment initiation, or automatic tax-liability advice in this capability.

## Feature 12.5 — Data Protection & Tax-Year Controls
- [ ] Feature complete
- [ ] Restrict tax packages and identifiers to authorized MANAGER/ADMIN users; encrypt sensitive identifiers/documents at rest and in backups, audit access/export, and redact secrets from logs.
- [ ] Apply tax-year-specific records, effective-dated rates/mappings, and retention policy; preserve source records and filed-return/payment confirmations according to the user-/preparer-configured retention schedule.
- [ ] Separate tax-workpaper mappings from management reporting categories so changing one does not silently alter the other.

## Feature 12.6 — Tax Reporting Tests
- [ ] Feature complete
- [ ] Test entity-dependent workpaper selection, date-period cutoffs, gross-to-net Square/1099-K reconciliation, refunds, sales tax and surtax reconciliation, COGS/inventory roll-forward, asset/mileage evidence exports, exception surfacing, role-based access, snapshot reproducibility, and no duplicate source amounts.
- [ ] Test that Florida individual income-tax forms are not generated and that state business-tax outputs remain conditional on configured applicability.
- [ ] Validate schedules against current official forms/instructions for each supported tax year and obtain tax-professional review before declaring any form mapping or calculation production-ready.
