## Backend toggles

All three returns toggles live in the **Returns** group on the backend form and ship
**off** by default:

| Toggle | Effect | Requirements |
| --- | --- | --- |
| **Sync Returns** | Includes this backend in the returns cron. | Marketplace ID set on the backend. |
| **Auto Restock Returns** | Creates an *un-validated* restock receipt (customer → stock) per return for the stockable returned products. The warehouse validates it on physical receipt. | The backend's **Warehouse** must have an incoming operation type (`in_type_id`); the receipt lands in that type's default destination, falling back to the warehouse stock location. Phase 1 books a plain incoming receipt — it is **not** chained to the original delivery. |
| **Auto Credit Note** | Creates and posts a credit note (`out_refund`) for the returned lines. | The originating Amazon order must have a linked sale order with a **posted customer invoice**. Accounts, taxes, unit price and the journal are copied from that invoice; returned products not on the invoice are logged and skipped. |

## Scheduled sync

The *Amazon: Sync Returns* scheduled action ships **disabled** (it calls the Reports
API). Enable it under **Settings → Technical → Scheduled Actions**; it runs every 12
hours and only pulls backends with **Sync Returns** ticked.
