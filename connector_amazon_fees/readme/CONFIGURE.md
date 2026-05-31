## Margin target

The fee-aware floor reuses the **Floor Margin %** field configured for competitive
pricing (**Amazon → Configuration → Backends → Pricing**, field
`competitive_floor_margin_pct`). With this module installed, that percentage is
interpreted as the **net** margin target the price must clear *after* Amazon's real
referral and fulfillment fees — not just `cost + margin%`. Set it once; both the
"Below Target Margin" flag and the repricing floor honor it.

## Per-listing FBA toggle

Each listing has an **FBA** checkbox (**Fees & Margin** group on the listing form).
Tick it for Fulfilled-by-Amazon SKUs so the `GetMyFeesEstimate` request includes FBA
fulfillment fees; leave it off for merchant-fulfilled SKUs (the estimate then omits
FBA fees). The flag is forwarded to Amazon as `is_amazon_fulfilled`.

## Scheduled sync

The *Amazon: Sync Fees* scheduled action ships **disabled** (it calls
`GetMyFeesEstimate` per SKU). Enable it under **Settings → Technical → Scheduled
Actions** to refresh estimates daily, or use the **Sync Fees** button on the backend
for an on-demand pull. Estimates are computed at each listing's current list price,
falling back to the buy-box price; priceless listings are skipped.
