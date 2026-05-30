1. Set the **MCF Default Speed** on the backend (Standard / Expedited /
   Priority) under **Amazon → Configuration → Backends**.
2. On an outgoing delivery whose products have FBA SKUs, click
   **Fulfill via Amazon**. A draft fulfillment order is created with one line
   per product (mapped to its FBA seller SKU) and the delivery address.
3. Review the lines and click **Submit to Amazon**. Amazon ships from FBA stock.
4. **Check Status** (or the *Amazon: Sync MCF Orders* scheduled action — it
   ships **disabled**; enable it under *Settings → Technical → Scheduled
   Actions* to poll automatically) updates the order; once Amazon ships it, the
   tracking number is written back to the delivery. Orders can be cancelled
   before they complete.

Find all fulfillment orders under **Amazon → Fulfillment → MCF Orders**.
