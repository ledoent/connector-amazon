Extends ``connector_amazon_pricing`` with a real-time buy-box change feed
via Amazon's SQS-backed ``ANY_OFFER_CHANGED`` notification stream.

Features:

- **SQS polling cron** — every 5 minutes, drains all pending
  ``ANY_OFFER_CHANGED`` messages and updates ``amz.listing`` buy-box
  fields (price, winner, pull timestamp).
- **Competitive repricing** — three rules: match buy box, undercut by %,
  or floor at cost + margin. Floors prevent selling below cost.
- **Competitor offer history** — every ``ANY_OFFER_CHANGED`` payload persists
  one ``amz.offer.snapshot`` per offer (seller, price, buy-box winner, ours or
  not), under **Amazon → Competitor Offers** — the basis for buy-box win-rate
  analytics.
- **Setup Notifications button** — registers the SQS destination and
  ``ANY_OFFER_CHANGED`` subscription with the SP-API Notifications API in
  one click.
- **Per-backend AWS credentials** — ``AWS Access Key ID``,
  ``AWS Secret Access Key``, ``AWS Region``, and ``SQS Queue URL`` stored
  per backend. Queue must be provisioned externally with the SP-API send
  policy attached.
- Requires ``boto3`` (``pip install boto3``) for SQS polling.

Messages that fail to parse are left on the queue (not deleted) so they can
be retried, so configure a **dead-letter queue** with a ``maxReceiveCount``
redrive policy on the source queue to shed permanently-malformed messages.
