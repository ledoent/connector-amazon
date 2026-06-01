## Syncing settlements

1. Open **Amazon → Configuration → Backends** and select a backend.
2. Make sure the **Settlement Accounting** group is configured (see CONFIGURE).
3. Click **Sync Settlements** in the form header to queue a pull immediately, or
   enable the *Amazon: Sync Settlements* scheduled action (Settings → Technical →
   Scheduled Actions) to pull every 6 hours.
4. The pull fetches every settlement group Amazon has marked **Closed** since the
   last sync (first run looks back 90 days). Open groups are skipped until Amazon
   closes them.

## Reading a settlement

Each closed group becomes an **amz.settlement.group** record, shown on the backend's
**Settlements** tab and at **Amazon → Finance**. Open one to see:

- **Financial Events** — every revenue/fee component (shipment, refund, referral fee,
  FBA fee, advertising, service fee, tax, shipping, promotion) parsed from Amazon's
  Finances payload. Positive = money in, negative = money out.
- **Reconciliation** — one row per Amazon order in the group, matching the settled
  Principal against the order's posted customer invoice.

The **Journal Entry** field links the posted `account.move`. One balanced entry is
posted per group: revenue buckets credited, fee buckets debited, the cash
disbursement debited to the settlement journal's account, and any residual booked to
an unclassified-adjustment line so the entry always balances.

## Reconciling against invoices

When orders are auto-invoiced by the Sales connector, open
**Amazon → Settlement Reconciliation** for a cross-settlement view:

1. Use the **Variances** / **Matched** / **No Invoice** filters to triage.
2. **Variance** rows (settled Principal ≠ invoiced untaxed total) are highlighted red;
   open one and use **Open Invoice** / **Amazon Order** to drill in.
3. **No Invoice** rows self-heal: once the invoice is posted, the next settlement sync
   re-runs reconciliation and flips them to **Matched** (no duplicate rows).
