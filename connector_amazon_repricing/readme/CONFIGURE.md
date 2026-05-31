## 1. Provision the SQS queue (AWS side)

This module consumes Amazon's `ANY_OFFER_CHANGED` feed via an SQS queue you own.
Odoo never creates the queue — provision it before configuring the backend.

1. In the AWS account, create a standard **SQS queue** in the region you will use
   (e.g. `us-east-1`).
2. Attach the **SP-API send policy** to the queue so Amazon's notification service
   can deliver to it. Amazon publishes from a fixed principal; grant
   `sqs:SendMessage` to the SP-API service on this queue's ARN (see the SP-API
   "Notifications" docs for the exact principal/condition).
3. Create a **dead-letter queue** and a redrive policy with a `maxReceiveCount`
   on the source queue. Messages that fail to parse are intentionally left on the
   queue (not deleted) so they retry; without a DLQ a permanently-malformed
   message would be redelivered forever.
4. Create an **IAM user** (or role) with `sqs:GetQueueAttributes`,
   `sqs:ReceiveMessage` and `sqs:DeleteMessage` on this queue, and generate an
   access key / secret for it.

## 2. Backend AWS credentials (Odoo side)

In **Amazon → Pricing → (your backend) → Real-Time Repricing (SQS)**:

- **AWS Access Key ID** / **AWS Secret Access Key** — the IAM user's key pair
  (stored masked in the form).
- **AWS Region** — the queue's region (default `us-east-1`).
- **SQS Queue URL** — the full queue URL from the SQS console. The queue ARN is
  derived from this automatically during **Setup Notifications**.
- **Real-Time Repricing** — master on/off switch for this backend.

`boto3` must be installed on the Odoo server (`pip install boto3`); the Setup and
poll actions raise a clear error if it is missing.

## 3. Enable the polling cron

The scheduled action **Amazon: Poll Offer Notifications (SQS)**
(`ir_cron_amz_poll_offer_notifications`) ships **disabled** because it makes live
AWS/SP-API calls. To enable:

1. **Settings → Technical → Automation → Scheduled Actions**.
2. Open **Amazon: Poll Offer Notifications (SQS)**, set it active (default every
   5 minutes).
3. It only drains backends where **Real-Time Repricing** is on and an SQS Queue
   URL is set.

Repricing on each notification additionally requires **Auto Price Push** (Pricing
module) and **Competitive** pricing mode; otherwise notifications only refresh
buy-box data and snapshots without pushing a new price.

## 4. Snapshot retention

`amz.offer.snapshot` is append-only and high-volume on popular ASINs. Add an
autovacuum / cleanup scheduled action that deletes rows older than your retention
window (filter on `date`) so the table does not grow unbounded.
