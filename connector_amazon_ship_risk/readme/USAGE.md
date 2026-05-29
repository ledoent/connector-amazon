1. Set the **Ship-Risk Threshold (hours)** on each backend
   (**Amazon → Configuration → Backends**) — the window before the cutoff in
   which an order is considered *At Risk* (default 24h). Optionally set a
   **Shipping Calendar** so the countdown uses working hours, making a
   Friday-evening cutoff with the weekend ahead read as urgent.
2. Order imports capture the ship-by cutoff and fulfillment channel
   automatically. Enable the *Amazon: Update Ship Risk* scheduled action so the
   countdown is refreshed as the clock advances (the risk is time-dependent).
3. Watch **Amazon → Sales → At-Risk Shipments**: overdue and stock-blocked
   orders are red, at-risk are amber, sorted soonest-cutoff first. The risk
   badge also appears on the standard order list and form.

Risk is only evaluated for open merchant-fulfilled orders; FBA orders (shipped
by Amazon) are left untouched.
