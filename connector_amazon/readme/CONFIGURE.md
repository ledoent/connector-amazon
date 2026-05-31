## Amazon Selling Partner API access

Before configuring a backend you need Login with Amazon (LWA) credentials for
the SP-API:

1. Register (or reuse) an SP-API application in **Seller Central > Apps &
   Services > Develop Apps**. You need the developer role on the selling
   account.
2. From the app, obtain the **LWA Client ID** and **LWA Client Secret**.
3. Authorize the app against your selling account and exchange the
   authorization for a long-lived **LWA Refresh Token**.
4. (Optional) For testing without touching live orders, create credentials in
   the **SP-API sandbox** and enable *Sandbox Mode* on the backend. Sandbox
   uses the reserved `TEST_CASE_200` query and the `sandbox.sellingpartnerapi-*`
   endpoints.

This module talks to SP-API directly over HTTPS via the
`python-amazon-sp-api` library (declared in `external_dependencies`); no AWS
IAM role or SQS queue is required.

## Backend configuration

Create a backend at **Amazon > Configuration > Backends** (requires the
*Amazon / Manager* group) and fill in:

| Field | Required | Notes |
|-------|----------|-------|
| **Backend Name** | yes | Free-text label. |
| **LWA Client ID** | yes | From your SP-API app. |
| **LWA Client Secret** | yes | Stored; visible only to *Settings* admins. |
| **LWA Refresh Token** | yes | Long-lived token; visible only to *Settings* admins. |
| **Marketplace** | yes | Selects the marketplace and its SP-API region (NA / EU / FE endpoint). Defaults to *US — amazon.com*. |
| **Sandbox Mode** | no | Use the SP-API sandbox endpoints and the `TEST_CASE_200` test query. Off for production. |
| **Company** | yes | Multi-company only; defaults to the current company. |
| **Warehouse** | yes | Source warehouse for orders/shipments; defaults to the company's first warehouse. |
| **Initial Import Days Back** | no | On the first import, fetch orders updated within this many days (default 7). |
| **Last Order Import** | read-only | Incremental polling cursor, advanced automatically. |

After saving, click **Test Connection** to verify credentials.

> The Client Secret and Refresh Token fields are restricted to the
> *Settings / Administration* group (`base.group_system`). Plain *Amazon /
> Manager* users can edit the backend but will not see those two fields.

## Scheduled import (cron)

The module ships an **Amazon: Import Orders** scheduled action
(`data/ir_cron.xml`) that polls every 5 minutes. It is **disabled by
default** so the connector never hits the live API until you opt in.

Enable it at **Settings > Technical > Automation > Scheduled Actions** *only
after* installing **connector_amazon_sale** — the cron calls
`backend.import_orders()`, which that module provides. With only the core
module installed the order import is a no-op (a warning is logged).
