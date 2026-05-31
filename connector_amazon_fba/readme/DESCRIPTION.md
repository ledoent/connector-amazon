Pulls **FBA (Fulfilment by Amazon) inventory** from the SP-API FBA Inventory
endpoint (`getInventorySummaries`) into `amz.fba.inventory` records and surfaces
the **drift** against Odoo on-hand, so discrepancies between what Amazon holds
and what Odoo thinks it holds are visible at a glance.

Per SKU it records the fulfillable, inbound (working + shipped + receiving),
reserved, unsellable, and total FBA quantities, snapshots the backend
warehouse on-hand, and computes ``drift = fulfillable − odoo_qty``.
Browse it under **Amazon → FBA Inventory**, with a **Drift** filter to surface
mismatches.

This module is **read-only** — it never writes to Amazon. A **Sync FBA
Inventory** button pulls on demand; the cron runs every 6 hours (disabled by
default). Enable per backend with **Sync FBA Inventory**.

FBA inbound-shipment creation and FBA-vs-FBM order routing are out of scope for
this module.
