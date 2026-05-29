This module adds an **Amazon → Dashboard** screen that rolls up health and key
metrics across the whole Amazon SP-API connector suite: orders, listings,
pricing & repricing, FBA inventory, settlements/reconciliation, and returns.

Each KPI is computed server-side (no custom JS) and the "problem" KPIs drill
straight into the relevant filtered list. An optional backend filter scopes
every figure to one marketplace; left empty it aggregates all active backends.
A single health badge turns red when there are failed jobs, settlement
variances, or FBA quantity drift.
