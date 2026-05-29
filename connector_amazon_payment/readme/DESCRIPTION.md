Pulls closed Amazon settlement groups via the SP-API Finances endpoint and
generates Odoo journal entries recording the net disbursement, Amazon fees
(referral, FBA, advertising, service), and gross sales revenue.

Each settlement group becomes an `amz.settlement.group` record with
`amz.financial.event` children for each revenue or fee component. A single
`account.move` is posted per group once all events are imported.

Configure the income account, fee account, advertising account, and settlement
journal on the Amazon backend record. The cron runs every 6 hours (disabled by
default).

Tax, shipping, and promotions are modeled to their own GL accounts (configure
the tax, shipping, and promotion accounts on the backend). Marketplace
Facilitator Tax that Amazon collects and remits nets to zero; only seller-liable
tax leaves a balance on the tax account. Any residual after modeling — typically
just currency rounding — is booked to an "unclassified adjustment" line so the
entry always balances and the real disbursement is preserved.

When orders are auto-invoiced (see the Sales connector), each settlement's
Principal is reconciled against the order's posted customer invoice; matches and
variances are listed under **Amazon → Settlement Reconciliation**.
