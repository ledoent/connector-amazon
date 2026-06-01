## Settlement accounting setup

On each backend (**Amazon → Configuration → Backends**), fill the
**Settlement Accounting** group before running the first sync:

| Field | Purpose |
| --- | --- |
| **Settlement Journal** | Journal for the disbursement entry. **Its default account is debited with the cash Amazon transfers** — without a default account the entry is skipped. A bank or general journal both work. |
| **Amazon Income Account** | Revenue account credited for sales (and the fallback that absorbs the unclassified-adjustment plug). |
| **Amazon Fee Account** | Expense account for referral, FBA, and service fees. |
| **Amazon Advertising Account** | Expense account for Amazon Advertising fees. Falls back to the Fee Account if blank. |
| **Amazon Tax Account** | Liability account for sales tax. Marketplace Facilitator Tax that Amazon collects and remits nets to zero here; only seller-liable tax leaves a balance. |
| **Amazon Shipping Account** | Revenue account for buyer-paid shipping and gift-wrap. Falls back to Income if blank. |
| **Amazon Promotion Account** | Contra-revenue account for seller-funded promotions/coupons. Falls back to Income if blank. |

Minimum to post an entry: a **Settlement Journal with a default account** plus an
**Income Account** and **Fee Account**. The optional tax/shipping/promotion/advertising
accounts only refine where those buckets land; when unset, their amounts fall into the
fallback accounts or the unclassified-adjustment line.

## Scheduled sync

The *Amazon: Sync Settlements* scheduled action ships **disabled** (it calls the
Finances API). Enable it under **Settings → Technical → Scheduled Actions** once
accounts are configured. It runs every 6 hours against every active backend.
