---
name: TrueMoney voucher payments
description: Durable payment-safety decisions for the bot's voucher subscriptions
---

- Subscription is granted only when the voucher amount matches a plan price
  exactly; unmatched amounts are flagged to the admin, never auto-granted.
  **Why:** removes ambiguity about which plan a payment buys.
- Payment-money invariants that must survive any refactor: a voucher code can be
  redeemed at most once even under concurrent submission; marking a voucher used
  and granting the entitlement must succeed or fail together; concurrent grants
  for one user must stack, not overwrite. **Why:** each was a real review-caught
  financial failure mode in the first implementation.
- The redemption provider is an unofficial third-party gateway supplied by the
  user. Do NOT treat payments as production-safe until the receiving wallet
  destination and provider are independently verified (tracked as a follow-up).
