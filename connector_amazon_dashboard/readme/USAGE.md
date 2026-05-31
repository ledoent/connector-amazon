## Opening the dashboard

Go to **Amazon → Dashboard** (top of the Amazon menu, visible to the *Amazon User*
group). The screen is a read-only roll-up — you can't create records on it.

## Scoping

The **Marketplace** selector at the top scopes every figure to one backend. Leave it
empty to aggregate across all active backends.

## Reading the KPIs

KPIs are grouped into sections — Sales, Pricing & Repricing, Fulfillment (FBA),
Settlements, Returns, and Operations Health. "Problem" figures highlight in red/amber
when non-zero and expose a **View →** link that drills straight into the relevant
filtered list (scoped to the same backend filter):

- **Unshipped** → orders not yet Shipped/Canceled/Unfulfillable.
- **Below Target Margin** → listings whose post-fee net margin is under the floor.
- **Price Changes (7d)** → recent repricing history.
- **FBA Drift SKUs** → SKUs where Amazon's fulfillable qty ≠ Odoo's on-hand.
- **Variances** → settlement reconciliation rows where settled ≠ invoiced.
- **Open Returns** → returns not yet credited/done.
- **Failed Jobs** → server-wide failed queue jobs (not backend-scoped).

## Health badge

The **System Health** badge turns red ("Needs Attention") whenever there are failed
jobs, settlement variances, FBA drift, or below-target-margin listings; otherwise it
reads green ("OK"). The **Sync Freshness** card shows the last sync timestamp for each
data source so you can spot a stalled cron at a glance.
