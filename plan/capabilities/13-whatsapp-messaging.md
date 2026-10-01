# Capability 13: WhatsApp Business Messaging

- [ ] **Capability complete** (all features below checked)

Bounded context: `mbs/messaging/`. Send an explicitly reviewed WhatsApp message from the application through the official Meta WhatsApp Business Platform Cloud API. This is a paid/usage-governed external integration, not the free `wa.me` handoff; current Meta pricing and platform rules apply.

## Feature 13.1 — Meta Account & API Setup 🧑‍💻 User Input Required
- [ ] Feature complete
- [ ] 🧑‍💻 Create/configure a Meta business portfolio, WhatsApp Business Account (WABA), Meta app, and registered business phone number; record the WABA ID and Phone Number ID.
- [ ] 🧑‍💻 Configure the app's WhatsApp product, approved permissions, production access, business verification as required, recipient test numbers, and an approved display name.
- [ ] Store access tokens, app secret, webhook verify token, and IDs as environment secrets/secrets-manager values; never store bearer tokens in `tbl_settings`, logs, browser code, or source control.
- [ ] Configure the current Graph API version explicitly and review Meta's current [WhatsApp Business Platform overview](https://developers.facebook.com/documentation/business-messaging/whatsapp/about-the-platform), [getting started](https://developers.facebook.com/documentation/business-messaging/whatsapp/get-started), and [pricing](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing) before production use.

## Feature 13.2 — Recipients, Consent & Templates
- [ ] Feature complete
- [ ] Maintain a WhatsApp recipient/contact record with E.164 phone number, display name, consent status, consent timestamp/source/purpose, locale, opt-out timestamp, and audit history; encrypt phone numbers at rest.
- [ ] Require documented recipient opt-in before any send. Suppress opted-out, invalid, or unconsented recipients in both UI and API; provide an immediate opt-out/suppression workflow.
- [ ] Outside the current customer-service window, allow only an approved Meta message template; inside the window, allow permitted free-form text. Check current Meta rules at send time and surface why a message type is unavailable.
- [ ] Keep approved template names, language, category, status, and parameter schema synchronized or admin-maintained; validate required parameters before queuing.
- [ ] Support a user-created send batch for two or more explicitly selected recipients, with an add-recipient control and no fixed UI recipient count. Enforce any configured safety cap and Meta's current limits; this is a manually initiated multi-recipient send, not a scheduled campaign or Marketing Messages API integration.
- [ ] Finalizing a market shopping list with a confirmed recipient selection is a manually initiated batch, not an automated campaign. Key the batch to that finalized list version and recipient set; retry/reconcile ambiguous delivery against the same attempt rather than sending another batch. A later receipt, change in made quantity, Square sale, or list edit never sends another message without a new explicit finalization/send action (D-53).
- [ ] Separately permit admin-configured, system-triggered utility alerts from approved application workflows (Capability 6.6), sent individually to configured, purpose-consented contacts using approved templates when required. This is not marketing automation and does not bypass opt-in, opt-out, service-window, or cost controls.

## Feature 13.3 — Compose & Send from the Application
- [ ] Feature complete
- [ ] Provide a MANAGER+ compose screen to select at least two consented recipients, add more recipients, choose free-form text or an approved template, preview the message for each recipient, and explicitly confirm Send.
- [ ] Send one private message per selected recipient through the Cloud API; this is not a WhatsApp group chat, and recipients must not see each other's phone numbers or message status.
- [ ] Provide an internal system-send path for configured utility alerts (Capability 6.6); it may send to one configured alert recipient per alert event and is exempt from the manual compose screen's two-recipient minimum, but still enforces opt-in, opt-out, approved-template/service-window, cost, idempotency, and delivery-status rules.
- [ ] Support plain text and approved template messages initially; validate E.164 addressing, text/template constraints, recipient consent, and service-window/template requirements before submission.
- [ ] Validate every recipient independently, prevent duplicate phone numbers in one batch, and show blocked/ineligible recipients before confirmation; do not silently send only part of the user's selection.
- [ ] Submit each message server-side through Meta's Cloud API `/{PHONE_NUMBER_ID}/messages`; never expose access tokens to the browser. Use per-recipient idempotency keys and persist provider message IDs and results under a parent send-batch record.
- [ ] Persist a `SUBMITTING` attempt before calling Meta. If the response is lost or ambiguous, reconcile by webhook/provider status and do not blindly resend; document that exactly-once delivery cannot be guaranteed across the external API boundary.
- [ ] Show current pricing basis and estimated batch cost when available; require an admin-configured spend/usage limit or confirmation threshold before sending beyond it. Do not label automated API sends free or hard-code rates.
- [ ] Provide `POST /api/v1/whatsapp/message-batches` (minimum two recipients), `GET /api/v1/whatsapp/message-batches/{id}`, and recipient/template lookup endpoints with role checks and request validation.

## Feature 13.4 — Delivery Webhooks, Status & Audit
- [ ] Feature complete
- [ ] Implement Meta webhook subscription, challenge verification, and request-signature validation; accept status updates for sent, delivered, read, and failed messages.
- [ ] Store parent batch status and per-recipient message status transitions, provider IDs/errors, recipient, template/type, timestamp, initiating user, and a restricted/audited message-content reference; report complete, partial, and failed batches and make webhook processing idempotent. Apply the configurable retention policy in Capability 2; without a configured period, do not automatically purge message records.
- [ ] Retry only transient failures with bounded backoff and provider error handling; never retry policy/consent/validation failures or create duplicate sends.
- [ ] Provide a searchable message history/status view for authorized users; enforce role checks and prevent sensitive content/phone numbers from appearing in ordinary application logs.

## Feature 13.5 — Development, Testing & Release
- [ ] Feature complete
- [ ] Use mocked Meta transport and synthetic numbers in CI; an optional provider sandbox smoke test uses a test WABA/phone after U-5 test setup. Manual sends require explicit confirmation and automated low-stock sends require an enabled admin rule plus valid recorded opt-in; no real recipient can be messaged in CI.
- [ ] Test the minimum-two recipient rule, adding more recipients, duplicate/ineligible recipient handling, per-recipient template rendering, partial batch failures, consent enforcement, opt-out suppression, E.164 validation, free-form/template window rules, idempotency, webhook replay, delivery-status transitions, and batch cost-limit blocks.
- [ ] Keep test credentials separate from production; add Meta secrets to `.env.example` as names/placeholders only and to deployment secret provisioning, never as actual values.
- [ ] Obtain user review of WhatsApp consent wording, privacy notice, retention period, and Meta business/account setup before production activation.
- [ ] Before production activation, retain a business-owner approval record for the WABA, phone number, display name, consent wording, privacy/retention treatment, spend threshold, webhook-signature verification, and a controlled opted-in-recipient smoke test. CI and development remain restricted to Meta test resources.
