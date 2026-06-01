1. Enable the sync per backend: open **Amazon → Configuration → Backends**, pick a
   backend, and tick **Sync FBA Inventory** (under the *FBA* section). Only ticked,
   active backends are pulled by the scheduled job.
2. Pull on demand at any time with the **Sync FBA Inventory** button in the backend
   form header — this queues a background job and does not wait for Amazon.
3. Browse the result under **Amazon → Fulfillment → FBA Inventory**. Each row is one
   seller SKU on one backend, with Amazon's fulfillable, inbound, reserved,
   unsellable and total FBA quantities, the matched Odoo product, and the backend
   warehouse on-hand.
4. **Drift** = fulfillable − backend warehouse on-hand. Use the **Drift** filter (or
   the amber row highlight) to surface SKUs where Amazon and Odoo disagree. Group by
   **Backend** when you run more than one marketplace.
5. **Last FBA Sync** on the backend form shows when the last successful pull finished.

This module is read-only — it never writes stock back to Amazon or to Odoo on-hand;
it only records what Amazon reports so you can see the discrepancy.
