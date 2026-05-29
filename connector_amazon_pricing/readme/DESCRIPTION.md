Extends ``connector_amazon`` to manage Amazon product listings and pricing.

Phase 1A features:

- ``amz.listing`` — one record per product/backend pair, acting as the central
  ledger for Amazon listing state (SKU, ASIN, current price, buy-box data).
- **Import Listings** button — bulk-populates ``amz.listing`` records from the
  Amazon Listings Items API.
- **Auto-create on order import** — when ``connector_amazon_sale`` imports an
  order line, any unregistered SKU with a matching Odoo product automatically
  gets an ``amz.listing`` record.
- **Push Prices** button — pushes Odoo pricelist prices to Amazon via the
  Listings Items PATCH API.
- Disabled cron template that syncs prices every 30 minutes.
- **Price-push audit trail** — every price push is logged to ``amz.price.history``
  (old → new price, pricing rule, trigger: manual / scheduled / offer
  notification), visible per listing and under **Amazon → Price History**.
