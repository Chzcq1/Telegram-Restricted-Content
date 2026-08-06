---
name: TrueMoney voucher payments
description: Durable rules for the bot's voucher subscription payments
---

- Payment model: customer sends a TrueMoney gift-voucher (angpao); redeeming it
  deposits the balance into `TRUEMONEY_WALLET_PHONE`. Subscription is granted by
  matching the voucher amount **exactly** to a plan price.
  **Why:** removes ambiguity about which plan a payment buys; unmatched amounts
  are flagged to the admin instead of auto-granting.
- Voucher claiming MUST be atomic before granting entitlement: claim the code
  (unique-insert wins for exactly one caller), redeem, then grant; release the
  claim if redemption fails so it can be retried.
  **Why:** a check-then-insert race let the same code be replayed for multiple
  subscriptions under concurrent submissions.
- The redemption provider is an unofficial third-party gateway supplied by the
  user. Do NOT treat payments as production-safe until the receiving wallet
  destination and provider are independently verified (tracked as a follow-up).
