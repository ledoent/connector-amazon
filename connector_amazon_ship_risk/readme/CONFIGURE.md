1. **Set the risk threshold per backend.** On each backend (**Amazon →
   Configuration → Backends**, *Shipping Risk* section) set **Ship-Risk Threshold
   (hours)** — the window before Amazon's ship-by cutoff inside which an open
   merchant order is flagged **At Risk** (default 24h).

2. **Optional working-hours countdown.** Set a **Shipping Calendar**
   (`resource.calendar`) to make the hours-to-cutoff countdown count *working* hours
   from that calendar instead of wall-clock time — so a Friday-evening cutoff with
   the weekend ahead reads as urgent rather than "many hours left". Leave it blank to
   use plain wall-clock hours.

3. **Enable the refresh cron.** Ship risk is time-dependent, so it is recomputed by a
   scheduled job, **Amazon: Update Ship Risk**, which ships **disabled**. Enable it
   under **Settings → Technical → Scheduled Actions** (runs every 30 minutes by
   default) so the countdown and risk states advance as deadlines approach. Risk is
   also recomputed once whenever an order is imported.

4. **Scope.** Only **open merchant-fulfilled (MFN)** orders are evaluated
   (Pending / PendingAvailability / Unshipped / PartiallyShipped). FBA (AFN) orders
   and shipped/cancelled orders are always left at *On Track*'s neutral "—".
