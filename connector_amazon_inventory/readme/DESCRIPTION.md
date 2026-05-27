Extends ``connector_amazon_pricing`` to push FBM (merchant-fulfilled) stock
quantities to Amazon via the Listings Items API.

On each sync cycle (default every 15 minutes):

1. For each active ``amz.listing`` with ``inventory_sync_enabled``, compute the
   available quantity from ``stock.quant`` records at the configured locations.
2. Apply backend-level rules: multiply by ``inventory_expose_ratio`` and subtract
   ``inventory_min_reserve``. Result is clamped to 0.
3. If the computed quantity differs from the last pushed value, send a
   ``PATCH /listings/.../fulfillment_availability`` request to Amazon.
4. Record ``last_pushed_qty`` and ``last_inventory_push_date`` on the listing.

Per-listing ``inventory_sync_enabled`` flag allows disabling sync for individual
SKUs (e.g. pre-orders or bundles handled outside Odoo).
