1. Set the **Buy Shipping Defaults** on the backend
   (**Amazon → Configuration → Backends**): default package weight, dimensions,
   their units, and the label format (PNG / PDF / ZPL).
2. On an Amazon delivery order, click **Buy Amazon Shipping**. The package
   weight is pre-filled from the moved products (falling back to the default).
3. Click **Get Rates** to fetch eligible Amazon carriers/services, then
   **Buy Label** on the option you want. The tracking number is written to the
   delivery, the label is attached, and an **Amazon Shipment** record is
   created (Amazon → Fulfillment → Amazon Shipments), where you can download
   the label.

The shipment is confirmed to Amazon as part of buying the label, so validating
the delivery will not send a duplicate tracking push.
