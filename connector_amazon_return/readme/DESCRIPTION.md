Ingests Amazon **MFN customer returns** via the SP-API Reports endpoint
(`GET_XML_RETURNS_DATA_BY_RETURN_DATE`) and turns each return into an
`amz.return` record with per-item lines (SKU, ASIN, quantity, reason), linked to
the originating Amazon order and — when present — the settlement refund event
captured by the Settlements connector.

The report is fetched asynchronously: a cron requests a report for the window
since the last sync, then fetches and parses it once Amazon marks it ``DONE``
(no worker blocks waiting). The cron runs every 12 hours (disabled by default);
a **Sync Returns** button triggers it on demand.

Two opt-in toggles on the backend (both off by default) automate the downstream:

- **Auto Restock Returns** — create an un-validated restock receipt
  (customer → stock) for the returned, stockable products. The warehouse
  validates it on physical receipt. Phase 1 books a plain incoming receipt; it
  is not chained to the original delivery.
- **Auto Credit Note** — create and post a credit note (``out_refund``) for the
  returned lines, mapped from the original customer invoice (accounts, taxes,
  unit price) and linked back to it and to the refund event.

Phase-1 boundaries: returned items are matched to invoice lines by product; a
returned product not present on the invoice is logged and skipped. FBA customer
returns (a separate report) are out of scope for this module.
