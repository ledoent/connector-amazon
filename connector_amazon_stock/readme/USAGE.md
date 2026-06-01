This module works automatically — there is no button or menu to click.

1. Install alongside **connector_amazon_sale** and import your Amazon orders so
   each has a linked `sale.order` and `amz.order` (see that module's USAGE).
2. Process the delivery for an Amazon order as usual: create/confirm the
   outgoing `stock.picking`, set the **Carrier** and a **Tracking Reference**
   on it, then validate it.
3. On validation, if the picking has both a tracking reference and a linked
   Amazon order, a background `queue_job` is enqueued to call Amazon's
   **ConfirmShipment** with the carrier code, tracking number, ship date, and
   shipped item quantities.
4. Carrier names are mapped to Amazon carrier codes automatically (UPS, USPS,
   FedEx, DHL, Amazon, OnTrac, LaserShip, UDS); any unrecognized carrier is
   sent as **"Other"**. To get a recognized code, name the Odoo delivery
   carrier with the carrier's name as a prefix (e.g. "UPS Ground").
5. If the picking has no tracking reference, no ship date, or no linked Amazon
   order, the push is skipped silently (logged at warning level) — no call is
   made to Amazon.
6. Monitor delivery results in **Settings > Technical > Queue Jobs** (the
   *Push tracking …* jobs); a failed push stays there and can be retried or
   inspected.
