## Estimating fees

1. On a backend (**Amazon → Configuration → Backends**), click **Sync Fees**, or
   enable the *Amazon: Sync Fees* scheduled action to refresh daily.
2. Each active listing with a price is sent to Amazon's `GetMyFeesEstimate` at
   its current list price (falling back to the buy-box price). The referral,
   FBA fulfillment, variable-closing and any other returned fees are stored,
   along with the resulting net proceeds and **net margin** per SKU.
3. Tick **FBA** on a listing so the estimate includes FBA fulfillment fees;
   leave it off for merchant-fulfilled SKUs.

## Reading the numbers

Listings show **Total Fees** and **Est. Margin %** columns; the
**Below Target Margin** filter surfaces SKUs whose net margin is under the
backend's floor margin. The dashboard rolls these up into *Avg Margin* and a
*Below Target Margin* count.

## Fee-aware repricing

When this module is installed, the competitive repricing floor in
`connector_amazon_pricing` becomes fee-aware: instead of `cost + margin%`, it
solves for the price whose net margin clears the target **after** Amazon's real
referral and fixed fees. Automated repricing therefore never quietly pushes a
price below your true break-even. Run **Sync Fees** before relying on it so the
estimates are current.
