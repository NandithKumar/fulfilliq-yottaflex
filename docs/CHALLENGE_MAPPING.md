# Challenge requirement traceability

| Challenge requirement | FulfillIQ implementation | Evidence / verification |
|---|---|---|
| Master entities generated first | SKU, node, carrier, service, carrier/service/zone bridge, calendars, holidays, inventory and capacity are built before order transactions. | `fulfilliq/generator.py`; SQLite FK constraints. |
| Child/event records use valid parent IDs | Every order line, shipment, shipment line, tracking event, promise and status event carries an explicit FK. | `fulfilliq/schema.py`; `PRAGMA foreign_key_check`. |
| Inventory by node | Node × SKU stock snapshot with on-hand, reserved, safety stock and available units. | `inventory.csv`; inventory balance and reservation reconciliation checks. |
| Carrier calendar, cutoffs, service zone and capacity | `carrier`, `carrier_calendar`, `carrier_service_zone`, `warehouse_capacity`. | Data dictionary; generator dispatch and promise helpers. |
| Single / split node allocation | One shipment for normal orders; explicit two-node split cohort; order-to-shipment 1:N. | `shipment.csv`, `shipment_line.csv`; split count and latest promise. |
| Delivery promises | Per-shipment dates plus one order-level promise. | `delivery_promise.csv`; chronology and latest-child validation. |
| Tracking events and actual delivery outcomes | Per-shipment ordered events; actual delivery derived from reliability rule and stable seed signal. | `tracking_event.csv`; event chronology checks. |
| Persist state as explicit history | `order_status_event` and append-only `tracking_event`; shipment rows represent current shipment state. | SQLite tables and order detail drawer. |
| Derived values from source records | Line totals, inventory/capacity balances, shipment totals, promise roll-ups and delivery labels calculated from source rows and rules. | Validator reconciliation queries. |
| All 11 core entities | All challenge entities are represented in SQLite and exports. | `schema.py` and exported table names. |
| PK/FK, cardinality, optional relationships, lifecycle | PK/FK/check/unique constraints, bridge tables, nullable unavailable promise dates, lifecycle documentation. | `schema.py`, generated `data_dictionary.md`, `ARCHITECTURE.md`. |
| Required deterministic ID conventions | ORD/FUL/SHP/TRK/PROM formats. | Generator and CSV exports. |
| 50,000 orders / 20 nodes / 10 carriers / 100,000 events | Full-scale command uses 50,000; 20; 10; 100,000 exactly. | `python -m fulfilliq.cli generate ...`; manifest counts. |
| Split shipments, holidays, capacity, carrier delays, unavailable stock | Split cohort, explicit synthetic closures, stressed capacity dates, delay rule and zero-stock SKU family. | Manifest; source rows; rule documentation. |
| Fixed seed, parameterized scale | Default seed `20261022`; `--orders`, `--nodes`, `--carriers`, `--skus` arguments. | CLI and `reproduce` command. |
| Five required negative scenarios | Five isolated cases with `issue_type`, expected detection and expected decision. | `ground_truth.json/csv`; ground-truth audit. |
| Validation of IDs, FKs, enums, dates, arithmetic and lifecycle | Database-backed validation suite. | `python -m fulfilliq.cli validate`. |
| CSV / JSON / SQL seed data | CSV and JSON exports plus `fulfilliq.db` SQLite seed database. | `data/generated/exports/` and `fulfilliq.db`. |
| README, schema/data dictionary, generator, seed, manifest and validation | Included and generated artifacts. | Root README, field-level `data_dictionary.md`, `source_manifest.json`, `validation_summary.json`, checksums and validation output. |
| Regenerate twice and compare checksums | `reproduce` runs two isolated generator builds and compares file hashes. | `python -m fulfilliq.cli reproduce`. |
| Public repository and meaningful commits | Ready for candidate's public GitHub repository. Git history is created locally; the candidate must create/push to their own public GitHub account. | Git setup instructions in final handoff; AI prompt log included. |
