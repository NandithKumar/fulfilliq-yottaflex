# Validation protocol

The validator queries the persisted SQLite database rather than relying on in-memory generator state. A passing run checks:

- Foreign-key integrity and primary-key/sequence uniqueness.
- Arithmetic: `line_total = quantity × unit_price`.
- Inventory and capacity balance equations.
- Shipment unit totals against the `shipment_line` bridge.
- Shipment-line parent-order consistency and allocation quantity upper bounds.
- Inventory reservations against shipment-line allocations by SKU and node.
- Daily capacity reservations against shipment totals by node and ship date.
- Promise dates against order dates and the latest child shipment promise.
- Nondecreasing tracking timestamps, snapshot chronology, pickup-after-dispatch and delivered-after-pickup.
- Shipment lifecycle alignment: a future handoff is `READY_TO_SHIP` with a packing event; `IN_TRANSIT` requires dispatch/pickup; delivered states require a delivery event.
- Order-level roll-up against every child shipment, plus final-state and timestamp consistency in the append-only order event history.
- Backorder orders having no shipment, and one promise row for each order.
- Exactly `2 × orders` tracking events for the assessment's suggested data ratio.
- Carrier/service/zone support for every generated shipment.

The pytest suite additionally exercises a feasible single-node preview and a multi-node split preview. The split test independently reconciles cumulative node/day capacity and SKU stock for each proposed line; it also verifies that the order promise is the latest child promise.

The separate ground-truth audit confirms all five required anomaly classes exist. It verifies fixture coverage; it does not expect intentionally invalid examples to pass baseline database checks.

## Reproducibility

`python -m fulfilliq.cli reproduce --orders 1000 --seed 20261022` builds the same scale twice in isolated temporary directories and compares SHA-256 checksums for every output file, including SQLite. Use `--orders 50000` for the full target if adequate disk and time are available.

Each generated output directory includes `validation_summary.json` with all check results and the separate ground-truth audit. The `source_manifest.json` also records the pass summary. `checksums.sha256` records the SHA-256 of the database, exported files, source manifest, data dictionary, validation summary and ground-truth fixtures. The checksum file itself is excluded from its own digest set.


## Verified full-scale run (seed `20261022`)

| Output | Observed |
|---|---:|
| Orders | 50,000 |
| Order lines | 98,650 |
| Fulfillment nodes | 20 |
| Carriers | 10 |
| SKUs | 500 |
| Shipments | 45,775 |
| Tracking events | 100,000 |
| Split orders | 1,378 |
| Backordered / capacity-exception orders | 5,603 |
| Order states: in transit / ready to ship | 5,603 / 1,730 |
| Shipment states: delivered / late / in transit / ready | 33,906 / 4,320 / 5,762 / 1,787 |
| Database validation | 30 / 30 passed |
| Ground-truth anomaly classes | 5 / 5 present |
| Same-seed artifact comparison | 40 files, 0 checksum mismatches |

The full-size second build was generated independently and compared against the persisted first build. The comparison covers SQLite, CSV, JSON, SQL seed, schema, manifest, field-level dictionary, validation summary and ground-truth artifacts.
