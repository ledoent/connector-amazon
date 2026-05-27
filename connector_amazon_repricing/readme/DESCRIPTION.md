Extends ``connector_amazon_pricing`` with a real-time buy-box change feed
via Amazon's SQS-backed ``ANY_OFFER_CHANGED`` notification stream.

Features:

- **SQS polling cron** — every 5 minutes, drains all pending
  ``ANY_OFFER_CHANGED`` messages and updates ``amz.listing`` buy-box
  fields (price, winner, pull timestamp).
- **Competitive repricing** — three rules: match buy box, undercut by %,
  or floor at cost + margin. Floors prevent selling below cost.
- **Setup Notifications button** — registers the SQS destination and
  ``ANY_OFFER_CHANGED`` subscription with the SP-API Notifications API in
  one click.
- **Per-backend AWS credentials** — ``AWS Access Key ID``,
  ``AWS Secret Access Key``, ``AWS Region``, and ``SQS Queue URL`` stored
  per backend. Queue must be provisioned externally with the SP-API send
  policy attached.
- Requires ``boto3`` (``pip install boto3``) for SQS polling.
