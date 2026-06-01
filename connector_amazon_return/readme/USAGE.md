## Enabling returns

1. On a backend (**Amazon → Configuration → Backends**), open the **Returns** group
   and tick **Sync Returns** to include this backend in the returns cron. (The
   per-backend toggle is separate from the cron's own enable switch.)
2. Optionally tick **Auto Restock Returns** and **Auto Credit Note** to automate the
   downstream (see CONFIGURE for what each does and what it needs).
3. Enable the *Amazon: Sync Returns* scheduled action to pull every 12 hours, or click
   **Sync Returns** on the backend form to pull on demand.

## How a return is pulled

Returns are fetched **asynchronously** via Amazon's Reports API
(`GET_XML_RETURNS_DATA_BY_RETURN_DATE`). One cron pass requests a report for the window
since the last sync (clamped to Amazon's 60-day max); a later pass fetches and parses it
once Amazon marks the report **DONE**. No worker blocks waiting. Report requests are
tracked as **amz.return.report** records (Requested → Done → Parsed, or Error on
FATAL/CANCELLED).

## Reading returns

Each return becomes an **amz.return** at **Amazon → Sales → Returns**, grouped by RMA,
with per-item lines (SKU, ASIN, quantity, reason). Open one to see:

- **Order** — the originating Amazon order, when matched.
- **Return Picking** — the restock receipt, if auto-restock is on.
- **Credit Note** — the posted `out_refund`, if auto-credit-note is on.
- **Refund Event** — the settlement refund line, if the Settlements connector captured
  one for the same order.

The **Status** column tracks New → Picking Created / Credited → Done. Use the
**New** / **Credited** filters and the **Status** group-by to triage.

## Self-healing

Re-ingesting the same RMA never duplicates the return, but it **does** create any
enabled-but-missing downstream artifact — so a return first ingested before its invoice
was posted gets its credit note on the next sync once the invoice exists.
