This guide assumes AWS/SQS and the backend are configured (see CONFIGURE).

## Activate real-time repricing

1. Open **Amazon → Pricing → (your backend)** and go to the **Real-Time
   Repricing (SQS)** section.
2. Tick **Real-Time Repricing** and confirm the four AWS fields are filled
   (Access Key ID, Secret Access Key, Region, SQS Queue URL).
3. Click **Setup Notifications** in the form header (the button only appears once
   an Access Key ID and an SQS Queue URL are present). This:
   - reads the queue ARN from your SQS URL,
   - registers an SP-API destination named `odoo-repricing-<backend>`,
   - subscribes the `ANY_OFFER_CHANGED` notification to it.
   A "Notifications Active" message confirms success; first messages arrive within
   ~5 minutes.

## How repricing runs

1. The scheduled action **Amazon: Poll Offer Notifications (SQS)** drains the
   queue every 5 minutes (see CONFIGURE to enable it).
2. For each `ANY_OFFER_CHANGED` message, the matching listing's **buy-box price**,
   **buy-box winner** and **pull timestamp** are updated, and one
   **Competitor Offer** snapshot per offer is recorded.
3. If the backend has **Auto Price Push** enabled (from the Pricing module) *and*
   is in **Competitive** pricing mode, the listing is repriced: a new target is
   computed from the competitive rule and, if it differs from the current price,
   PATCHed to Amazon. Each such change is logged to Price History with the
   **Offer Notification** trigger.

## Buy-box / competitor analytics

1. Open **Amazon → Pricing → Competitor Offers** (`amz.offer.snapshot`).
2. Each row is one offer seen on an ASIN: seller, price, "Our Offer", "Buy Box
   Winner". Your offers are bold; buy-box-winning rows are highlighted green.
3. Filter by **Our Offers** / **Buy Box Winner**, or group by **Listing** /
   **Seller**, to compute buy-box win-rate over time.
4. This table is append-only and grows fast on busy ASINs — schedule a cleanup
   (see CONFIGURE).
