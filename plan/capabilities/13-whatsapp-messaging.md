# Capability 13: WhatsApp Business Messaging

Database: PostgreSQL only; see [D-77](../00-overview.md#postgresql-contract-all-stages).
- [ ] Test send/outbox/version identity, concurrent claims, webhook retry, rollback/savepoints, one local event/source. Call provider after commit, without row locks.

- [ ] **Capability complete** (all features below checked)

Bounded context: `mbs/messaging/`. Sends reviewed messages through paid Meta WhatsApp Cloud API, not `wa.me`; current pricing/rules apply.

## Feature 13.1 — Meta Account & API Setup 🧑‍💻 User Input Required
- [ ] Feature complete
- [ ] 🧑‍💻 Create/configure a Meta business portfolio, WhatsApp Business Account (WABA), Meta app, and registered business phone number; record the WABA ID and Phone Number ID.
- [ ] 🧑‍💻 Configure the app's WhatsApp product, approved permissions, production access, business verification as required, recipient test numbers, and an approved display name.
- [ ] Store access tokens, app secret, webhook verify token, and IDs as environment secrets/secrets-manager values; never store bearer tokens in `tbl_settings`, logs, browser code, or source control.
- [ ] Configure the current Graph API version explicitly and review Meta's current [WhatsApp Business Platform overview](https://developers.facebook.com/documentation/business-messaging/whatsapp/about-the-platform), [getting started](https://developers.facebook.com/documentation/business-messaging/whatsapp/get-started), and [pricing](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing) before production use.

## Feature 13.2 — Recipients, Consent & Templates
- [ ] Feature complete
- [ ] Store E.164, display name, locale, consent status/time/source/purpose, opt-out time, audit history; encrypt phone numbers.
- [ ] Require documented recipient opt-in before any send. Suppress opted-out, invalid, or unconsented recipients in both UI and API; provide an immediate opt-out/suppression workflow.
- [ ] Outside the current customer-service window, allow only an approved Meta message template; inside the window, allow permitted free-form text. Check current Meta rules at send time and surface why a message type is unavailable.
- [ ] Keep approved template names, language, category, status, and parameter schema synchronized or admin-maintained; validate required parameters before queuing.
- [ ] Allow manually initiated batches to ≥2 selected recipients; support add-recipient without fixed UI limit. Enforce safety cap/Meta limits. No scheduled campaign or Marketing Messages API.
- [ ] Finalized list + confirmed recipients starts one manual batch keyed to list version/recipient set. Retry/reconcile the same attempt; later receipts, made quantities, sales, or edits never resend without explicit new finalization/send (D-53).
- [ ] Separately allow Cap 6.6 admin-configured utility alerts to purpose-consented contacts, individually, with required templates. Not marketing; retain opt-in/out, service-window, cost controls.

## Feature 13.3 — Compose & Send from the Application
- [ ] Feature complete
- [ ] Provide a MANAGER+ compose screen to select at least two consented recipients, add more recipients, choose free-form text or an approved template, preview the message for each recipient, and explicitly confirm Send.
- [ ] Send private one-recipient Cloud API messages; never expose other recipients' numbers/status.
- [ ] Provide an internal system-send path for configured utility alerts (Capability 6.6); it may send to one configured alert recipient per alert event and is exempt from the manual compose screen's two-recipient minimum, but still enforces opt-in, opt-out, approved-template/service-window, cost, idempotency, and delivery-status rules.
- [ ] Support plain text and approved template messages initially; validate E.164 addressing, text/template constraints, recipient consent, and service-window/template requirements before submission.
- [ ] Validate every recipient independently, prevent duplicate phone numbers in one batch, and show blocked/ineligible recipients before confirmation; do not silently send only part of the user's selection.
- [ ] Submit server-side to `/{PHONE_NUMBER_ID}/messages`; never expose tokens to browser. Use per-recipient idempotency keys; persist provider IDs/results under parent batch.
- [ ] Persist a `SUBMITTING` attempt before calling Meta. If the response is lost or ambiguous, reconcile by webhook/provider status and do not blindly resend; document that exactly-once delivery cannot be guaranteed across the external API boundary.
- [ ] Show current pricing basis and estimated batch cost when available; require an admin-configured spend/usage limit or confirmation threshold before sending beyond it. Do not label automated API sends free or hard-code rates.
- [ ] Provide `POST /api/v1/whatsapp/message-batches` (minimum two recipients), `GET /api/v1/whatsapp/message-batches/{id}`, and recipient/template lookup endpoints with role checks and request validation.

## Feature 13.4 — Delivery Webhooks, Status & Audit
- [ ] Feature complete
- [ ] Implement Meta webhook subscription, challenge verification, and request-signature validation; accept status updates for sent, delivered, read, and failed messages.
- [ ] Store batch/per-recipient transitions, provider IDs/errors, recipient, template/type, time, initiator, restricted audited content reference. Report complete/partial/failed; webhook idempotent. Apply Cap 2 retention; no configured period means no auto-purge.
- [ ] Retry only transient failures with bounded backoff and provider error handling; never retry policy/consent/validation failures or create duplicate sends.
- [ ] Provide a searchable message history/status view for authorized users; enforce role checks and prevent sensitive content/phone numbers from appearing in ordinary application logs.

## Feature 13.5 — Development, Testing & Release
- [ ] Feature complete
- [ ] Use mocked Meta transport and synthetic numbers in CI; an optional provider sandbox smoke test uses a test WABA/phone after U-5 test setup. Manual sends require explicit confirmation and automated low-stock sends require an enabled admin rule plus valid recorded opt-in; no real recipient can be messaged in CI.
- [ ] Test the minimum-two recipient rule, adding more recipients, duplicate/ineligible recipient handling, per-recipient template rendering, partial batch failures, consent enforcement, opt-out suppression, E.164 validation, free-form/template window rules, idempotency, webhook replay, delivery-status transitions, and batch cost-limit blocks.
- [ ] Keep test credentials separate from production; add Meta secrets to `.env.example` as names/placeholders only and to deployment secret provisioning, never as actual values.
- [ ] Obtain user review of WhatsApp consent wording, privacy notice, retention period, and Meta business/account setup before production activation.
- [ ] Before production activation, retain a business-owner approval record for the WABA, phone number, display name, consent wording, privacy/retention treatment, spend threshold, webhook-signature verification, and a controlled opted-in-recipient smoke test. CI and development remain restricted to Meta test resources.
