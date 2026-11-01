# Technical walkthrough: 8–10 minutes

## 1. Frame the problem (45 seconds)

“FulfillIQ is a local fulfillment decision system. It selects a fulfillment node and carrier using stock, per-node daily capacity, service/zone coverage and carrier cutoffs. It then calculates a defensible promise date, records shipment/tracking history and rolls child outcomes up to the order.”

## 2. Show the operating view (90 seconds)

Open the Control Tower. Explain that the KPIs are derived from generated relational records. Point to the 45-day flow, state distribution, node capacity pulse and exception watchlist. Emphasize that this is a local simulation, not a live carrier integration.

## 3. Trace one order (2 minutes)

Open Order Command and select an order with multiple shipments. Walk through the order lines, shipment-to-node assignment, separate carrier promises and event ledger. Explain why the order promise is the latest child-shipment promise and why one delivered package cannot complete a split order.

## 4. Run a decision preview (2 minutes)

Open Allocation Lab. The default scenario uses an open synthetic capacity day and the SKU picker is ordered by network-wide available stock. Run the default preview first to show a feasible single-node decision, then increase the quantity or choose a low-stock SKU to demonstrate the exception path. Select a service level, destination zone and SKU basket as needed. Run the preview. Explain the feasibility gates, candidate ranking score, carrier cutoff and calendar-aware dispatch date. Show either a single-node recommendation or a split/escalation outcome. State that the endpoint is read-only and intentionally does not reserve inventory.

## 5. Show network health (60 seconds)

Point to utilization by node and the carrier reliability scorecard. Clarify that carrier rates and closure dates are fictional scenario inputs.

## 6. Prove data quality (90 seconds)

Open Data Assurance. Show the SQL-backed checks. Explain that the five challenge anomalies are isolated in ground truth, not smuggled into baseline input data.

## 7. Explain reproducibility (60 seconds)

Show `source_manifest.json`, the seed `20261022`, `checksums.sha256`, then run `python -m fulfilliq.cli reproduce --orders 1000 --seed 20261022`. Explain that the generator uses the same pipeline for starter and full scale.

## Questions to be ready for

- Why is the order promise the maximum of split shipment promises? Because the customer needs the complete basket, not just the first parcel.
- What happens after cutoff? The dispatch date advances to the next operational carrier date, and capacity is checked against that date.
- Why no ML model? The challenge is deterministic constraint satisfaction and traceable synthetic data. An opaque prediction model would complicate correctness and would not replace stock/capacity feasibility.
- How are actual delays produced? A deterministic hash signal is compared with the synthetic carrier on-time parameter; delay days are then derived from the same seed and shipment ID.
- Is the preview transactional? No. It is explicitly read-only. A production reservation API would require atomic inventory/capacity reservation, concurrency control and idempotency.
- What is not production-ready? Carrier calendars/reliability are synthetic; no carrier API, WMS/OMS integration, customer PII, real payment data or live notifications are included.
