## Backend pricing settings

Open **Amazon → Pricing → (your backend)** and fill the **Pricing** section:

- **Amazon Seller ID** — Merchant Token from Seller Central → Account Info →
  Merchant Token. Required for **Import Listings** and **Push Prices**.
- **Pricing Mode**:
  - *Odoo Pricelist* — pushes the price from the backend's pricelist
    (`pricelist_id`, configured by `connector_amazon_sale`).
  - *Amazon Competitive Floor* — prices against the live buy box (see rules below).
  - *Manual / No Sync* — never computes or pushes a price (Push Prices button hidden).
- **Auto Price Push** — when on, this backend is included in the scheduled sync.

### Competitive mode rules (shown only in Competitive mode)

- **Competitive Rule**:
  - *Match Buy Box* — target = current buy-box price.
  - *Undercut Buy Box by %* — target = buy box × (1 − Undercut %).
  - *Floor: Cost + Margin %* — competes at the buy box but never below the floor.
- **Undercut %** — only shown for the undercut rule; e.g. `1.0` = 1% under buy box.
- **Floor Margin %** — applied to *every* competitive rule as a hard floor:
  target is never below `standard_price × (1 + Floor Margin % / 100)`. If the buy
  box is below the floor, the listing is priced at the floor instead of matching.

A computed price needs a buy-box price on the listing — run **Sync Competitive
Prices** (or enable the cron) before expecting a push in competitive mode.

## Scheduled action

The cron **Amazon: Sync Prices** (`ir_cron_amz_sync_prices`) ships **disabled**
(`active=False`) because it makes live SP-API calls. To enable:

1. Go to **Settings → Technical → Automation → Scheduled Actions**.
2. Open **Amazon: Sync Prices**, set it active, adjust the interval if needed
   (default every 30 minutes).
3. It only acts on backends where **Auto Price Push** is enabled.

## Permissions

- **Amazon Manager** (`group_amz_manager`) — full read/write on listings and price
  history.
- **Amazon User** (`group_amz_user`) — read-only.
