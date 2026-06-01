This guide assumes the backend and listings are already set up via
`connector_amazon_pricing` (see that module's USAGE), and that this module's
backend settings are configured (see CONFIGURE).

## Enable inventory sync on a listing

1. Open **Amazon → Pricing → Listings** and pick a listing.
2. On the form, under **Inventory**, tick **Sync Inventory** (on by default for
   new listings). Untick it for SKUs whose Amazon stock you manage elsewhere
   (pre-orders, bundles, FBA-only items).
3. The same flag, plus **Last Pushed Qty** and **Last Inventory Push** date, also
   appear as optional columns on the backend's Listings tab.

## Push stock to Amazon

1. On the backend form, confirm **Inventory Sync** is enabled and the **Amazon
   Seller ID** (Pricing section) is set — the push errors without it.
2. Click **Push Inventory** in the form header (shown only when **Inventory Sync**
   is on). This queues a job that, for every active listing with **Sync
   Inventory** on:
   - computes the FBM quantity (see CONFIGURE for the formula),
   - skips listings whose quantity is unchanged since the last push,
   - PATCHes `fulfillment_availability` to Amazon for the rest,
   - records **Last Pushed Qty** and **Last Inventory Push** on the listing.
3. A stock-out is pushed too: when a previously-nonzero SKU drops to 0, a
   `quantity: 0` update is sent so Amazon stops offering it.

## Automatic inventory sync

1. Enable **Inventory Sync** on the backend.
2. Enable the **Amazon: Push Inventory** scheduled action (ships disabled — see
   CONFIGURE). It runs every 15 minutes across all backends with Inventory Sync on.
