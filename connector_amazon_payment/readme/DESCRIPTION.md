Pulls closed Amazon settlement groups via the SP-API Finances endpoint and
generates Odoo journal entries recording the net disbursement, Amazon fees
(referral, FBA, advertising, service), and gross sales revenue.

Each settlement group becomes an `amz.settlement.group` record with
`amz.financial.event` children for each revenue or fee component. A single
`account.move` is posted per group once all events are imported.

Configure the income account, fee account, advertising account, and settlement
journal on the Amazon backend record. The cron runs every 6 hours (disabled by
default).
