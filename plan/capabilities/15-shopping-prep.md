# Capability 15: Market Shopping & Prep

- [ ] **Capability complete** (all features below checked)

Bounded context: `src/mbs/prep/`. Owns planned market loads, store-grouped shopping lists, and confirmed prep events. It consumes markets from Capability 5, recipes/costs from Capability 4, the MVP 3 lightweight stock-balance interface in MVP 4, and the full Capability 6 inventory interface after MVP 6. It delegates outbound WhatsApp transport to Capability 13. A plan is not a purchase, production, sale, or inventory movement until explicitly confirmed.

## Feature 15.1 — Market Load Lists
- [ ] Feature complete
- [ ] Provide a Market Load List for a selected market visit date using the saved Market ID; allow product Variation ID, target quantity, notes, and prep status.
- [ ] Save lists by market/date and allow copying a prior list while editing quantities without duplicating market identities.
- [ ] For perishable items, default editable `Perishable By` to exactly seven days after the new list item's creation timestamp; leave it blank for non-perishables and preserve explicit overrides when copying lists.

## Feature 15.2 — Store-Grouped Shopping Lists
- [ ] Feature complete
- [ ] Calculate ingredient and stocked-supply requirements from product targets, recipe quantities, units, and waste percentages; aggregate shared inputs and include expected waste in net-to-buy estimates. Surface missing recipes or incompatible units rather than silently omitting needs.
- [ ] Subtract available ingredient and supply balances from approved purchases and prior confirmed prep; present estimates separately from actual purchases. Planned estimates do not post inventory movements or accrue waste.
- [ ] In MVP 4, read balances only through the MVP 3 lightweight stock-balance interface using its approved purchase, opening-count, and confirmed-prep movements. Do not depend on Capability 6 tables/jobs or maintain a separate shopping balance; Capability 6 later implements the same interface with reconciled inventory.
- [ ] Group requirements by preferred or selected purchase store/location; allow manual item additions, quantity adjustments, and store reassignment.
- [ ] Include item, quantity/unit, Perishable status, optional estimated unit/line cost, last-purchase location, and Product URL where available. Provide a print-friendly page/PDF per store; keep store purchase lists separate from Market Load Lists.
- [ ] Render selected store lists as readable line-delimited text and send through Capability 13's consent-checked WhatsApp interface; validate text/template limits and retain print/export as fallback.
- [ ] Marking items purchased or completing a list does not automatically create purchases. Provide an explicit action to record approved purchases through Capability 4 with vendor/location, actual quantity, and actual cost.

## Feature 15.3 — Confirmed Prep Posting
- [ ] Feature complete
- [ ] An explicit prep confirmation creates or links one shared production event through Capability 5's production service and posts recipe-ingredient consumption, product production, and market-supply usage exactly once.
- [ ] The shared production service is an MVP 4 prerequisite. Test retry, concurrent confirmation, failure rollback, correction, and later MVP 5 manual production against one production-event identity and one set of stock movements.
- [ ] Apply each recipe input's waste percentage and carry discrete-unit fractions forward across events/weeks until a whole waste unit is reached; fractional-capable units post exact waste quantities. Corrections reverse/recompute affected movements and remainders idempotently.
- [ ] Associate all movements with the market visit/date and copy `Perishable By` onto resulting perishable stock lots. Unconfirmed plans have no effect on inventory, production, sales, or profit.

## Feature 15.4 — APIs & Test Coverage
- [ ] Feature complete
- [ ] Provide `GET/POST /api/v1/markets/prep-lists` and `GET/PUT /api/v1/markets/prep-lists/{id}` with date, market, and status filters and MANAGER+ write authorization.
- [ ] The MVP 4 `prep-mvp` profile in Capability 10 covers list calculations, expected waste, store grouping/printing, WhatsApp payloads, unposted-plan isolation, and atomic confirmed-prep posting.
