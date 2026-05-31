This guide assumes the backend is already configured (see CONFIGURE).

## Import your Amazon listings

1. Go to **Amazon → Pricing → (your backend)** and open the backend form.
2. Make sure **Amazon Seller ID** is set under the **Pricing** section (the
   Merchant Token from Seller Central → Account Info → Merchant Token). Imports
   fail with an error if it is empty.
3. Click **Import Listings** in the form header. This calls the Listings Items
   API and creates one **Amazon Listing** (`amz.listing`) per SKU that matches an
   Odoo product by Internal Reference (`default_code`). SKUs with no matching
   product are skipped (logged as a warning). Pagination is followed
   automatically, so all pages import in one click.
4. A "Listings Imported" notification reports how many records were created or
   updated. Re-running is safe — existing listings are updated in place
   (ASIN / product), never duplicated.

Listings auto-create on order import too: when `connector_amazon_sale` imports an
order, any new SKU with a matching Odoo product gets an `amz.listing` automatically.

## Review listings

1. Open **Amazon → Pricing → Listings** for the full list, or use the
   **Listings** tab on the backend form.
2. Each listing shows SKU, ASIN, the linked product, current list price, buy-box
   price, computed target price and the last push timestamp.

## Push prices to Amazon

1. Choose a **Pricing Mode** on the backend (see CONFIGURE for what each mode does).
2. In **Competitive** mode, click **Sync Competitive Prices** first to pull the
   current buy-box prices from Amazon into the listings (this button is only shown
   in competitive mode).
3. Click **Push Prices** in the form header (shown in every mode except *Manual*).
   This queues a background job that, for each active listing, computes the target
   price for the current mode and PATCHes it to Amazon via the Listings Items API.
4. Every price *change* is recorded in **Amazon → Pricing → Price History**
   (`amz.price.history`): old price, new price, the pricing rule used, and the
   trigger (Manual / Scheduled / Offer Notification). Unchanged prices are not
   logged, so the history stays signal-only.

## Automatic price sync

1. Enable **Auto Price Push** on the backend.
2. Enable the **Amazon: Sync Prices** scheduled action (ships disabled — see
   CONFIGURE). It runs every 30 minutes and, for each backend with **Auto Price
   Push** on, pulls competitive prices (competitive mode only) then pushes.
