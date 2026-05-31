1. **Enable the backends you want synced.** Open **Amazon → Configuration →
   Backends**, and for each backend tick **Sync FBA Inventory** in the *FBA*
   section. Backends left unticked are skipped by the scheduled job (the manual
   **Sync FBA Inventory** button still works on any backend).

2. **Enable the scheduled pull.** The cron **Amazon: Sync FBA Inventory** ships
   **disabled**. To poll automatically, enable it under **Settings → Technical →
   Scheduled Actions**. It runs every 6 hours by default and enqueues one pull job
   per enabled, active backend; adjust the interval there to taste.

3. **SKU matching.** FBA rows are linked to Odoo products by **Internal Reference**
   (`default_code`) matching Amazon's seller SKU. SKUs with no matching product are
   still recorded (so the drift is visible) but have no product and an Odoo on-hand
   of 0.

4. **Warehouse.** Drift is computed against the **on-hand of the backend's
   warehouse**, not global on-hand, so each backend must have its **Warehouse** set
   for the comparison to be meaningful.
