To use the Amazon connector:

1. Open the **Amazon** top menu (visible to users in the *Amazon / User*
   group).
2. Go to **Amazon > Configuration > Backends** and open (or create) the
   backend record for your Selling Partner account. Creating and editing
   backends requires the *Amazon / Manager* group.
3. With credentials filled in (see CONFIGURE), click **Test Connection** in
   the backend form header. A green *Connection successful* notification
   confirms Odoo can reach the SP-API and reports how many recent orders were
   returned; a red error means the credentials or marketplace are wrong.
4. Imported Amazon orders appear under **Amazon > Sales > Orders** as
   `amz.order` staging records, each showing the Amazon order ID, status,
   fulfillment channel (Merchant/MFN or Amazon/FBA), totals, and the linked
   Odoo sale order once one exists.
5. Open an Amazon order to see its **Order Lines** tab (ASIN, Seller SKU,
   quantities, item price, tax) and, via the **Sale Order** stat button, jump
   to the Odoo `sale.order` it was mapped to.
6. Use the search filters **Unshipped** and **Not Imported**, or group by
   **Backend** / **Amazon Status**, to triage orders.

> The core module only stores and displays orders. To actually import orders
> into `sale.order`, install **connector_amazon_sale**; to push tracking
> numbers back to Amazon, install **connector_amazon_stock**.
