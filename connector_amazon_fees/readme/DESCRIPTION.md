This module pulls Amazon's **GetMyFeesEstimate** for each listing and stores
the fee breakdown — referral fee, FBA fulfillment fee, variable closing fee —
alongside the resulting **net proceeds and net margin** per SKU.

Two things it unlocks:

- **Profitability visibility.** Every listing shows what Amazon actually keeps
  and what margin is left after cost, with a "below target margin" flag for
  quick triage.
- **A fee-aware repricing floor.** When this module is installed, the
  competitive repricing floor stops guessing: instead of `cost + margin%`, it
  solves for the price whose net margin clears the target *after* Amazon's real
  referral and fulfillment fees, so automated repricing never quietly sells
  below your true break-even.

Fees are estimated at the listing's current list price (falling back to the
buy-box price), via a manual **Sync Fees** button or a daily cron.
