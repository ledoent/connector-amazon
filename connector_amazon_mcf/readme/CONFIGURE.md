1. **MCF Default Speed.** On each backend (**Amazon → Configuration → Backends**,
   *Multi-Channel Fulfillment* section) choose the default shipping speed —
   **Standard**, **Expedited** or **Priority** — pre-filled onto each new
   fulfillment order. It can be overridden per order before submitting.

2. **Status polling (optional).** The cron **Amazon: Sync MCF Orders** ships
   **disabled**. Enable it under **Settings → Technical → Scheduled Actions** to
   poll submitted/processing orders automatically (every 2 hours by default) and
   write the returned tracking number back onto the Odoo delivery. Without it, use
   the **Check Status** button on each order.
