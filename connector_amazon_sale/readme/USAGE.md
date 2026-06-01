To import Amazon orders into Odoo:

1. Configure the backend credentials first (see the **connector_amazon**
   module's CONFIGURE), then open the backend at **Amazon > Configuration >
   Backends**.
2. In the **Import Settings** group, optionally set:
   - **Sales Team** — assigned to every imported sale order.
   - **Pricelist** — applied to imported orders (defaults to the company
     pricelist).
   - **Auto-Invoice Orders** — when ticked, each imported order is confirmed
     and a customer invoice is created and posted automatically.
3. Make sure your sellable products carry their Amazon **Seller SKU** in the
   product's **Internal Reference** (`default_code`). Order lines are matched
   to products by this field.
4. Click **Import Orders Now** in the backend form header to pull orders on
   demand, or enable the **Amazon: Import Orders** scheduled action to poll
   automatically every 5 minutes.
5. Each Amazon order updated since the last import cursor is fetched; orders in
   *Canceled* / *Unfulfillable* status are skipped. For every other order Odoo
   creates or reuses a customer from the shipping address, creates a
   `sale.order` (lines mapped to products by Seller SKU), and links it to the
   `amz.order` staging record.
6. Review imported orders under **Amazon > Sales > Orders**. Lines whose SKU
   has no matching Odoo product are still created as description-only sale
   lines (never silently dropped) — search for them and assign products as
   needed.
7. If **Auto-Invoice Orders** is on, open the linked sale order to find the
   posted customer invoice under its Invoices.
