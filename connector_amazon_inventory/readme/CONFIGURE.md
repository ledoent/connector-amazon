## Backend inventory settings

In **Amazon → Pricing → (your backend) → Inventory Sync**:

- **Inventory Sync** — master switch for this backend (off by default). Enables the
  **Push Inventory** button and includes the backend in the scheduled push.
- **Fulfillment Locations** — the internal stock locations counted toward the
  Amazon FBM quantity. Leave empty to use the warehouse's default stock location
  (`warehouse_id.lot_stock_id`).
- **Expose Ratio** — fraction of free stock to expose to Amazon, `0.0`–`1.0`
  (validated). E.g. `0.5` exposes half. Default `1.0`.
- **Min Reserve** — units always held back regardless of ratio (validated ≥ 0).
  Default `0`.

The pushed quantity per SKU is:

    free_qty = Σ over the configured locations of max(0, on_hand − reserved)
    pushed   = max(0, floor(free_qty × Expose Ratio) − Min Reserve)

`free_qty` already nets out reserved stock; the result is floored to a whole unit,
then Min Reserve is subtracted, then clamped to 0. **Amazon Seller ID** (Pricing
section) is required for any push.

## Per-listing override

Each listing has its own **Sync Inventory** flag (on by default). Unchecking it
excludes that SKU from both the manual button and the cron — useful for
pre-orders, bundles, or SKUs fulfilled outside Odoo.

## Scheduled action

The cron **Amazon: Push Inventory** (`ir_cron_amz_push_inventory`) ships
**disabled** (makes live SP-API calls). Enable it under **Settings → Technical →
Automation → Scheduled Actions** (default every 15 minutes). It acts only on
backends with **Inventory Sync** on.
