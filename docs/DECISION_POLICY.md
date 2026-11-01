# Allocation and promise policy

## Feasibility gates

A candidate is eligible only when all of the following hold:

1. The node is active.
2. Every requested SKU has at least the requested quantity in `inventory.available` at that node.
3. Daily warehouse capacity on the calculated dispatch date can cover the order's handling-unit total.
4. The carrier supports the order's requested service level and destination zone.
5. A valid carrier operating date exists in the generated calendar horizon.

The generator reserves no more than the available SKU quantity and no more than the node/date capacity. A failed feasibility gate yields an explicit backorder/carrier exception rather than a silent partial allocation. A shipment with a scheduled handoff later than the simulation snapshot remains `READY_TO_SHIP`; it is not represented as moving before the pickup timestamp.

## Candidate score

The simulation ranks feasible candidates with a transparent heuristic:

`score = transit_days × 10 + carrier_base_cost × 0.08 + zone_gap × 2 − remaining_capacity_ratio × 3 − on_time_rate × 4`

Lower scores rank earlier. `zone_gap` is 0 for a same-zone node and 1 otherwise. This is a prioritization heuristic, not a learned probability model. It is intentionally simple enough to explain and test.

## Cutoff and dispatch

- The order timestamp is interpreted with its explicit local UTC offset.
- Orders at or before a carrier's local cutoff can dispatch on the same date if the carrier is operational.
- Orders after cutoff, on a closed weekday or on a closure date move to the next operational date.
- The selected `ship_date` is the dispatch date used for warehouse capacity reservation.

## Promise calculation

For a shipment, the earliest and latest delivery dates are calculated by adding the selected service level's minimum and maximum business transit days to the dispatch date. Carrier non-operating weekdays and generated closure dates are skipped. The shipment's committed promise is the latest date in that window. The order-level promise is the maximum promised date across every child shipment, which represents the date by which all split packages should have arrived.

## Actual outcome generation

A SHA-256-derived stable score from `(seed, shipment_id, "delay")` is compared with `1 - carrier.on_time_rate`. When the signal falls within that delay threshold, the shipment receives one to three additional carrier business days. Otherwise, actual delivery equals the committed promise date. This creates variation while retaining exact reproducibility. The outcome label is calculated from the date comparison, not assigned independently.

## Split allocation and order roll-up

The generator includes a small, explicitly counted split cohort. Its order lines are split across two separately feasible nodes to exercise the one-order / many-shipments relationship and latest-child promise logic. An order can be marked delivered only when every child shipment is delivered. The order promise uses the latest shipment promise. This prevents a fast first parcel from prematurely closing an order whose second parcel is still moving.

## Exception behavior

- `INVENTORY_UNAVAILABLE`: at least one order line uses a SKU family with zero available units across the network.
- `CAPACITY_LIMIT`: no candidate node/date can handle the complete order within the remaining daily capacity.
- `CARRIER_UNSUPPORTED`: no carrier supports the requested service level and destination zone.
- The five deliberately invalid challenge scenarios are isolated in `ground_truth.json` and have expected detection/decision labels. They never contaminate the baseline tables.

## Preview API safety

`POST /api/decision` is read-only. It validates the request, queries current balances, returns ranked candidates and an explainable recommendation, and does not mutate inventory, capacity or shipment history. Production reservation would require a transaction with optimistic locking or an atomic reservation ledger; that is intentionally outside this preview endpoint.


## Live allocation preview

The read-only preview ranks carrier/node candidates using the same stock, service-zone, cutoff/calendar and node/date capacity gates. If no single node can serve the basket, the split planner walks the order lines using local remaining-stock and remaining-capacity ledgers. It decrements both per proposed line, so separate lines cannot independently pass and collectively overbook the same SKU/node or node/dispatch-date. The returned order-level promise is the maximum of the proposed child-shipment promises. The preview does not persist reservations; a production commit would still need atomic transactions and concurrency controls.
