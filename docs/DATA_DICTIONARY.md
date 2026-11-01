# FulfillIQ field-level data dictionary

## Conventions

- SQLite storage types are `TEXT`, `INTEGER` and `REAL`. CSV exports preserve IDs as strings.
- All timestamps are ISO-8601 with an explicit UTC offset. All date-only values are `YYYY-MM-DD`.
- Monetary values are INR (₹); weights are kilograms; capacity and inventory quantities are whole units; reliability values are ratios from 0 to 1.
- `Required` means non-null for a baseline row. Fields marked `Optional` may be null only where stated.
- IDs are immutable and zero-padded where the challenge prescribes a pattern. Synthetic customer IDs are pseudonymous and contain no personal data.
- `ground_truth.json/csv` is evaluation metadata, not a baseline operational entity and must not be loaded as an input feature.

## Master and reference entities

### `sku` (primary key: `sku_id`)

| Field | Type | Req. | Allowed values / unit | Unique | Validation rule |
|---|---|---:|---|---:|---|
| `sku_id` | TEXT | Yes | `SKU-######` | Yes | Immutable SKU identifier. |
| `name` | TEXT | Yes | Synthetic product name | No | Non-empty. |
| `category` | TEXT | Yes | `ELECTRONICS`, `HOME`, `APPAREL`, `BEAUTY`, `SPORTS`, `BOOKS`, `GROCERY` | No | Must be in category enum. |
| `unit_weight_kg` | REAL | Yes | kg, greater than 0 | No | Positive. |
| `unit_price` | REAL | Yes | INR, >= 0 | No | Non-negative. |
| `is_active` | INTEGER | Yes | 0 or 1 | No | Boolean. |

### `fulfillment_node` (primary key: `node_id`)

| Field | Type | Req. | Allowed values / unit | Unique | Validation rule |
|---|---|---:|---|---:|---|
| `node_id` | TEXT | Yes | `FUL-2026-######` | Yes | Immutable node ID. |
| `name` | TEXT | Yes | Synthetic facility name | No | Non-empty. |
| `city` | TEXT | Yes | Synthetic Indian city | No | Non-empty. |
| `state` | TEXT | Yes | State/UT code label | No | Non-empty. |
| `zone` | TEXT | Yes | `NORTH`, `SOUTH`, `EAST`, `WEST`, `CENTRAL` | No | Must be in zone enum. |
| `node_type` | TEXT | Yes | `FULFILLMENT_CENTER`, `DARK_STORE`, `STORE` | No | Must be in node-type enum. |
| `latitude` | REAL | Yes | Decimal degrees | No | -90 to 90. |
| `longitude` | REAL | Yes | Decimal degrees | No | -180 to 180. |
| `is_active` | INTEGER | Yes | 0 or 1 | No | Boolean. |

### `carrier` (primary key: `carrier_id`)

| Field | Type | Req. | Allowed values / unit | Unique | Validation rule |
|---|---|---:|---|---:|---|
| `carrier_id` | TEXT | Yes | `CAR-###` | Yes | Immutable carrier ID. |
| `name` | TEXT | Yes | Fictional carrier name | Yes | Non-empty. |
| `cutoff_time` | TEXT | Yes | Local `HH:MM` | No | Must parse as a valid 24-hour time. |
| `operating_days` | TEXT | Yes | Comma-separated weekdays, 0=Mon…6=Sun | No | Every value must be 0–6. |
| `on_time_rate` | REAL | Yes | Ratio [0,1] | No | Inclusive range check. |
| `base_cost` | REAL | Yes | INR | No | Non-negative. |
| `handling_hours` | INTEGER | Yes | Hours >= 0 | No | Non-negative integer. |

### `service_level` (primary key: `service_level_id`)

| Field | Type | Req. | Allowed values / unit | Unique | Validation rule |
|---|---|---:|---|---:|---|
| `service_level_id` | TEXT | Yes | `SVC-STD`, `SVC-EXP`, `SVC-ECO`, `SVC-PRI` | Yes | Immutable reference ID. |
| `name` | TEXT | Yes | `STANDARD`, `EXPRESS`, `ECONOMY`, `PRIORITY` | Yes | Must be in service enum. |
| `min_transit_days` | INTEGER | Yes | Business days | No | >= 0. |
| `max_transit_days` | INTEGER | Yes | Business days | No | >= min transit days. |
| `priority_rank` | INTEGER | Yes | Positive rank | No | >= 1; lower means higher priority. |

### `carrier_service_zone` (composite primary key: `carrier_id`, `service_level_id`, `zone`)

| Field | Type | Req. | Allowed values / unit | Unique | Validation rule |
|---|---|---:|---|---:|---|
| `carrier_id` | TEXT | Yes | Existing carrier ID | Composite | FK to `carrier`. |
| `service_level_id` | TEXT | Yes | Existing service ID | Composite | FK to `service_level`. |
| `zone` | TEXT | Yes | Five network zones | Composite | Must be in zone enum. |
| `avg_transit_days` | REAL | Yes | Business days | No | >= 0. |
| `supported` | INTEGER | Yes | 0 or 1 | No | Boolean; only value 1 may be selected for shipment. |
| `surcharge` | REAL | Yes | INR | No | >= 0. |

### `carrier_calendar` (composite primary key: `carrier_id`, `service_date`)

| Field | Type | Req. | Allowed values / unit | Unique | Validation rule |
|---|---|---:|---|---:|---|
| `carrier_id` | TEXT | Yes | Existing carrier ID | Composite | FK to `carrier`. |
| `service_date` | TEXT | Yes | ISO date | Composite | Valid date within generated horizon. |
| `is_operational` | INTEGER | Yes | 0 or 1 | No | Boolean. |
| `holiday_name` | TEXT | Optional | Synthetic closure name | No | Null unless date is a configured closure. |

### `public_holiday` (primary key: `holiday_date`)

| Field | Type | Req. | Allowed values / unit | Unique | Validation rule |
|---|---|---:|---|---:|---|
| `holiday_date` | TEXT | Yes | ISO date | Yes | Valid date. |
| `holiday_name` | TEXT | Yes | Synthetic closure description | No | Non-empty. |
| `zone` | TEXT | Yes | `ALL` or a network zone | No | Must be a valid zone or `ALL`. |

## Transaction entities

### `orders` (primary key: `order_id`)

| Field | Type | Req. | Allowed values / unit | Unique | Validation rule |
|---|---|---:|---|---:|---|
| `order_id` | TEXT | Yes | `ORD-2026-######` | Yes | Immutable order ID. |
| `customer_id` | TEXT | Yes | Synthetic `CUS-######` | No | Pseudonymous; no personal details. |
| `order_ts` | TEXT | Yes | ISO-8601 timestamp + UTC offset | No | Must parse; must not exceed snapshot. |
| `destination_zone` | TEXT | Yes | Five network zones | No | Must be in zone enum. |
| `destination_city` | TEXT | Yes | Synthetic destination city | No | Non-empty. |
| `priority` | TEXT | Yes | `STANDARD`, `HIGH`, `CRITICAL` | No | Must be in priority enum. |
| `requested_service_level_id` | TEXT | Yes | Existing service ID | No | FK to `service_level`. |
| `order_status` | TEXT | Yes | `CREATED`, `BACKORDERED`, `CARRIER_REVIEW`, `READY_TO_SHIP`, `IN_TRANSIT`, `DELIVERED`, `DELIVERED_LATE` | No | Must agree with child shipment roll-up and lifecycle. |
| `issue_type` | TEXT | Optional | `INVENTORY_UNAVAILABLE`, `CAPACITY_LIMIT`, `CARRIER_UNSUPPORTED` | No | Null for normal orders; populated for an exception. |

### `order_line` (primary key: `line_id`; unique: `order_id`,`sku_id`)

| Field | Type | Req. | Allowed values / unit | Unique | Validation rule |
|---|---|---:|---|---:|---|
| `line_id` | TEXT | Yes | `LIN-<order-seq>-##` | Yes | Immutable line ID. |
| `order_id` | TEXT | Yes | Existing order ID | No | FK to `orders`. |
| `sku_id` | TEXT | Yes | Existing SKU ID | No | FK to `sku`; one SKU per order. |
| `quantity` | INTEGER | Yes | Whole units > 0 | No | Positive integer. |
| `unit_price` | REAL | Yes | INR | No | >= 0; copied from SKU at order creation. |
| `line_total` | REAL | Yes | INR | No | Must reconcile to `quantity × unit_price` within ₹0.01. |

### `inventory` (primary key: `inventory_id`; unique: `node_id`,`sku_id`)

| Field | Type | Req. | Allowed values / unit | Unique | Validation rule |
|---|---|---:|---|---:|---|
| `inventory_id` | TEXT | Yes | `INV-<node-seq>-<sku-seq>` | Yes | Immutable snapshot row ID. |
| `node_id` | TEXT | Yes | Existing node ID | Composite | FK to `fulfillment_node`. |
| `sku_id` | TEXT | Yes | Existing SKU ID | Composite | FK to `sku`. |
| `on_hand` | INTEGER | Yes | Units >= 0 | No | >= 0. |
| `reserved` | INTEGER | Yes | Units >= 0 | No | <= on-hand; reconciles to allocated shipment lines. |
| `safety_stock` | INTEGER | Yes | Units >= 0 | No | >= 0. |
| `available` | INTEGER | Yes | Units >= 0 | No | Exactly `max(0,on_hand-reserved-safety_stock)`. |
| `updated_at` | TEXT | Yes | ISO-8601 timestamp + UTC offset | No | Inventory snapshot effective time. |

### `warehouse_capacity` (primary key: `capacity_id`; unique: `node_id`,`capacity_date`)

| Field | Type | Req. | Allowed values / unit | Unique | Validation rule |
|---|---|---:|---|---:|---|
| `capacity_id` | TEXT | Yes | `CAP-<node-seq>-YYYYMMDD` | Yes | Immutable capacity row ID. |
| `node_id` | TEXT | Yes | Existing node ID | Composite | FK to `fulfillment_node`. |
| `capacity_date` | TEXT | Yes | ISO date | Composite | Effective date of capacity. |
| `total_units` | INTEGER | Yes | Handling units >= 0 | No | >= 0. |
| `reserved_units` | INTEGER | Yes | Handling units >= 0 | No | <= total; reconciles to shipment units by node/date. |
| `available_units` | INTEGER | Yes | Handling units >= 0 | No | Exactly `total_units-reserved_units`. |

### `shipment` (primary key: `shipment_id`)

| Field | Type | Req. | Allowed values / unit | Unique | Validation rule |
|---|---|---:|---|---:|---|
| `shipment_id` | TEXT | Yes | `SHP-2026-######` | Yes | Immutable shipment ID. |
| `order_id` | TEXT | Yes | Existing order ID | No | FK to `orders`; an order may have multiple shipments. |
| `node_id` | TEXT | Yes | Existing node ID | No | FK to `fulfillment_node`. |
| `carrier_id` | TEXT | Yes | Existing carrier ID | No | FK to `carrier`; selected route must be supported. |
| `service_level_id` | TEXT | Yes | Existing service ID | No | FK to `service_level`; matches parent order request. |
| `ship_date` | TEXT | Yes | ISO date | No | Planned dispatch date, derived from cutoff/calendar. |
| `dispatch_ts` | TEXT | Optional | ISO-8601 timestamp + UTC offset | No | Null only for a not-yet-dispatched shipment; otherwise >= order time. |
| `status` | TEXT | Yes | `READY_TO_SHIP`, `IN_TRANSIT`, `DELIVERED`, `DELIVERED_LATE` | No | `READY_TO_SHIP` has no dispatch timestamp and requires `PACKED`; dispatched shipments require `PICKED_UP`; delivered statuses require a valid delivery event. |
| `total_units` | INTEGER | Yes | Handling units > 0 | No | Must equal shipment-line quantity sum. |
| `tracking_number` | TEXT | Yes | `YF` + 12 digits | Yes | Unique carrier-independent synthetic tracking code. |
| `promised_delivery_date` | TEXT | Yes | ISO date | No | Must not precede order date; derived from service window. |
| `actual_delivery_date` | TEXT | Optional | ISO date | No | Null until delivered; if present must not precede dispatch date. |

### `shipment_line` (composite primary key: `shipment_id`,`line_id`)

| Field | Type | Req. | Allowed values / unit | Unique | Validation rule |
|---|---|---:|---|---:|---|
| `shipment_id` | TEXT | Yes | Existing shipment ID | Composite | FK to `shipment`. |
| `line_id` | TEXT | Yes | Existing order-line ID | Composite | FK to `order_line`; must belong to the same parent order as shipment. |
| `quantity` | INTEGER | Yes | Whole units > 0 | No | Positive; total allocated per order line cannot exceed ordered quantity. |
| `unit_price` | REAL | Yes | INR | No | >= 0; copied from source order line. |

### `tracking_event` (primary key: `event_id`; unique: `shipment_id`,`sequence_no`)

| Field | Type | Req. | Allowed values / unit | Unique | Validation rule |
|---|---|---:|---|---:|---|
| `event_id` | TEXT | Yes | `TRK-<shipment-id>-###` | Yes | Immutable event ID; sequence zero-padded. |
| `shipment_id` | TEXT | Yes | Existing shipment ID | No | FK to `shipment`. |
| `sequence_no` | INTEGER | Yes | Positive integer | Composite | Unique per shipment; starts at 1. |
| `event_code` | TEXT | Yes | `LABEL_CREATED`, `PACKED`, `PICKED_UP`, `IN_TRANSIT`, `DELIVERED` | No | Must be in tracking enum. |
| `event_ts` | TEXT | Yes | ISO-8601 timestamp + UTC offset | No | Nondecreasing by sequence; delivered cannot precede pickup. |
| `location` | TEXT | Yes | Synthetic city/location | No | Non-empty. |
| `description` | TEXT | Yes | Human-readable event detail | No | Non-empty. |

### `delivery_promise` (primary key: `promise_id`; unique: `order_id`)

| Field | Type | Req. | Allowed values / unit | Unique | Validation rule |
|---|---|---:|---|---:|---|
| `promise_id` | TEXT | Yes | `PROM-<order-id>-01` | Yes | Immutable promise ID. |
| `order_id` | TEXT | Yes | Existing order ID | Yes | FK to `orders`; exactly one simulation row per order. |
| `promised_delivery_date` | TEXT | Conditional | ISO date | No | Required unless status is `UNAVAILABLE`; never before order date. |
| `earliest_delivery_date` | TEXT | Conditional | ISO date | No | Required unless status is `UNAVAILABLE`; <= latest promise. |
| `latest_delivery_date` | TEXT | Conditional | ISO date | No | Required unless status is `UNAVAILABLE`; equals the committed order promise. |
| `calculation_version` | TEXT | Yes | Engine version string | No | Non-empty; supports rule/version traceability. |
| `reason_code` | TEXT | Yes | `LATEST_SPLIT_SHIPMENT`, `NODE_CAPACITY_AND_SERVICE_OPTIMIZED`, `INVENTORY_UNAVAILABLE`, `CAPACITY_LIMIT`, `CARRIER_UNSUPPORTED` | No | Explains how promise or no-promise state was reached. |
| `calculated_at` | TEXT | Yes | ISO-8601 timestamp + UTC offset | No | Calculation timestamp. |
| `promise_status` | TEXT | Yes | `PENDING`, `ON_TIME`, `LATE`, `UNAVAILABLE` | No | Derived from all child shipment outcomes and availability. |

### `order_status_event` (primary key: `order_event_id`; unique: `order_id`,`sequence_no`)

| Field | Type | Req. | Allowed values / unit | Unique | Validation rule |
|---|---|---:|---|---:|---|
| `order_event_id` | TEXT | Yes | `OEV-<order-id>-##` | Yes | Immutable event ID. |
| `order_id` | TEXT | Yes | Existing order ID | No | FK to `orders`. |
| `from_status` | TEXT | Optional | `CREATED`, `ALLOCATED`, `BACKORDERED`, `CARRIER_REVIEW`, `READY_TO_SHIP`, `IN_TRANSIT`, `DELIVERED`, `DELIVERED_LATE` | No | Null only for initial event. |
| `to_status` | TEXT | Yes | `CREATED`, `ALLOCATED`, `BACKORDERED`, `CARRIER_REVIEW`, `READY_TO_SHIP`, `IN_TRANSIT`, `DELIVERED`, `DELIVERED_LATE` | No | Append-only transition target. |
| `event_ts` | TEXT | Yes | ISO-8601 timestamp + UTC offset | No | Nondecreasing within an order; cannot exceed snapshot. |
| `reason` | TEXT | Yes | Human-readable transition reason | No | Non-empty. |
| `sequence_no` | INTEGER | Yes | Positive integer | Composite | Unique per order; starts at 1. |

## Relationships and effective dates

| Relationship | Cardinality | Optionality / enforcement |
|---|---|---|
| Order → OrderLine | 1:N | OrderLine requires its parent order. |
| Order → Shipment | 1:N | A backordered order may have zero shipments. |
| Order → DeliveryPromise | 1:1 | A row is retained for every order; date fields are null for `UNAVAILABLE`. |
| Order → OrderStatusEvent | 1:N | Initial state event has no `from_status`; subsequent events retain history. |
| SKU → OrderLine / Inventory | 1:N | SKU parents are required. |
| FulfillmentNode → Inventory / WarehouseCapacity / Shipment | 1:N | Node parents are required. |
| OrderLine ↔ Shipment | N:M | Resolved by `shipment_line`; quantity is allocated at bridge-row level. |
| Carrier ↔ ServiceLevel + zone | N:M | Resolved by `carrier_service_zone`; unsupported rows are ineligible. |
| Carrier → CarrierCalendar | 1:N | Date-effective service availability. |
| Shipment → TrackingEvent | 1:N | Events are append-only and sequence-numbered. |

**Effective dating:** inventory is a point-in-time snapshot (`updated_at`); warehouse capacity is keyed by node/date; carrier operating availability is keyed by carrier/date; service-zone support is a versioned reference mapping for this generated horizon. The simulation preserves state-change history in `order_status_event` and `tracking_event` rather than overwriting prior event records.

**Lifecycle:** Order: `CREATED` → `ALLOCATED` (recorded in order history) → `READY_TO_SHIP` / `IN_TRANSIT` → `DELIVERED` / `DELIVERED_LATE`; exceptions: `BACKORDERED`, `CARRIER_REVIEW`. Shipment: `READY_TO_SHIP` (labelled/packed, no carrier handoff yet) → `IN_TRANSIT` (pickup/handoff recorded) → `DELIVERED` / `DELIVERED_LATE`. A future dispatch remains `READY_TO_SHIP` as of the snapshot. Promise: `PENDING`, `ON_TIME`, `LATE`, `UNAVAILABLE`.
