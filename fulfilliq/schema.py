"""SQLite schema. Every relationship is explicit and enforced by foreign keys."""
SCHEMA_SQL = r"""
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS sku (
  sku_id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
  unit_weight_kg REAL NOT NULL CHECK(unit_weight_kg > 0), unit_price REAL NOT NULL CHECK(unit_price >= 0),
  is_active INTEGER NOT NULL CHECK(is_active IN (0,1))
);
CREATE TABLE IF NOT EXISTS fulfillment_node (
  node_id TEXT PRIMARY KEY, name TEXT NOT NULL, city TEXT NOT NULL, state TEXT NOT NULL,
  zone TEXT NOT NULL CHECK(zone IN ('NORTH','SOUTH','EAST','WEST','CENTRAL')),
  node_type TEXT NOT NULL CHECK(node_type IN ('FULFILLMENT_CENTER','DARK_STORE','STORE')),
  latitude REAL NOT NULL, longitude REAL NOT NULL, is_active INTEGER NOT NULL CHECK(is_active IN (0,1))
);
CREATE TABLE IF NOT EXISTS carrier (
  carrier_id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, cutoff_time TEXT NOT NULL,
  operating_days TEXT NOT NULL, on_time_rate REAL NOT NULL CHECK(on_time_rate BETWEEN 0 AND 1),
  base_cost REAL NOT NULL CHECK(base_cost >= 0), handling_hours INTEGER NOT NULL CHECK(handling_hours >= 0)
);
CREATE TABLE IF NOT EXISTS service_level (
  service_level_id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
  min_transit_days INTEGER NOT NULL, max_transit_days INTEGER NOT NULL,
  priority_rank INTEGER NOT NULL, CHECK(min_transit_days >= 0 AND max_transit_days >= min_transit_days)
);
CREATE TABLE IF NOT EXISTS carrier_service_zone (
  carrier_id TEXT NOT NULL REFERENCES carrier(carrier_id),
  service_level_id TEXT NOT NULL REFERENCES service_level(service_level_id),
  zone TEXT NOT NULL, avg_transit_days REAL NOT NULL CHECK(avg_transit_days >= 0),
  supported INTEGER NOT NULL CHECK(supported IN (0,1)), surcharge REAL NOT NULL DEFAULT 0,
  PRIMARY KEY(carrier_id, service_level_id, zone)
);
CREATE TABLE IF NOT EXISTS carrier_calendar (
  carrier_id TEXT NOT NULL REFERENCES carrier(carrier_id), service_date TEXT NOT NULL,
  is_operational INTEGER NOT NULL CHECK(is_operational IN (0,1)), holiday_name TEXT,
  PRIMARY KEY(carrier_id, service_date)
);
CREATE TABLE IF NOT EXISTS public_holiday (
  holiday_date TEXT PRIMARY KEY, holiday_name TEXT NOT NULL, zone TEXT NOT NULL DEFAULT 'ALL'
);
CREATE TABLE IF NOT EXISTS orders (
  order_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, order_ts TEXT NOT NULL,
  destination_zone TEXT NOT NULL, destination_city TEXT NOT NULL,
  priority TEXT NOT NULL CHECK(priority IN ('STANDARD','HIGH','CRITICAL')),
  requested_service_level_id TEXT NOT NULL REFERENCES service_level(service_level_id),
  order_status TEXT NOT NULL CHECK(order_status IN ('CREATED','BACKORDERED','CARRIER_REVIEW','READY_TO_SHIP','IN_TRANSIT','DELIVERED','DELIVERED_LATE')),
  issue_type TEXT CHECK(issue_type IS NULL OR issue_type IN ('INVENTORY_UNAVAILABLE','CAPACITY_LIMIT','CARRIER_UNSUPPORTED'))
);
CREATE TABLE IF NOT EXISTS order_line (
  line_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(order_id),
  sku_id TEXT NOT NULL REFERENCES sku(sku_id), quantity INTEGER NOT NULL CHECK(quantity > 0),
  unit_price REAL NOT NULL CHECK(unit_price >= 0), line_total REAL NOT NULL CHECK(line_total >= 0),
  UNIQUE(order_id, sku_id)
);
CREATE TABLE IF NOT EXISTS inventory (
  inventory_id TEXT PRIMARY KEY, node_id TEXT NOT NULL REFERENCES fulfillment_node(node_id),
  sku_id TEXT NOT NULL REFERENCES sku(sku_id), on_hand INTEGER NOT NULL CHECK(on_hand >= 0),
  reserved INTEGER NOT NULL CHECK(reserved >= 0), safety_stock INTEGER NOT NULL CHECK(safety_stock >= 0),
  available INTEGER NOT NULL CHECK(available >= 0), updated_at TEXT NOT NULL,
  CHECK(reserved <= on_hand), CHECK(available = MAX(0, on_hand - reserved - safety_stock)),
  UNIQUE(node_id, sku_id)
);
CREATE TABLE IF NOT EXISTS warehouse_capacity (
  capacity_id TEXT PRIMARY KEY, node_id TEXT NOT NULL REFERENCES fulfillment_node(node_id),
  capacity_date TEXT NOT NULL, total_units INTEGER NOT NULL CHECK(total_units >= 0),
  reserved_units INTEGER NOT NULL CHECK(reserved_units >= 0),
  available_units INTEGER NOT NULL CHECK(available_units >= 0),
  CHECK(reserved_units <= total_units), CHECK(available_units = total_units - reserved_units),
  UNIQUE(node_id, capacity_date)
);
CREATE TABLE IF NOT EXISTS shipment (
  shipment_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(order_id),
  node_id TEXT NOT NULL REFERENCES fulfillment_node(node_id),
  carrier_id TEXT NOT NULL REFERENCES carrier(carrier_id),
  service_level_id TEXT NOT NULL REFERENCES service_level(service_level_id),
  ship_date TEXT NOT NULL, dispatch_ts TEXT,
  status TEXT NOT NULL CHECK(status IN ('READY_TO_SHIP','IN_TRANSIT','DELIVERED','DELIVERED_LATE')),
  total_units INTEGER NOT NULL CHECK(total_units > 0), tracking_number TEXT NOT NULL UNIQUE,
  promised_delivery_date TEXT NOT NULL, actual_delivery_date TEXT
);
CREATE TABLE IF NOT EXISTS shipment_line (
  shipment_id TEXT NOT NULL REFERENCES shipment(shipment_id),
  line_id TEXT NOT NULL REFERENCES order_line(line_id),
  quantity INTEGER NOT NULL CHECK(quantity > 0), unit_price REAL NOT NULL CHECK(unit_price >= 0),
  PRIMARY KEY(shipment_id, line_id)
);
CREATE TABLE IF NOT EXISTS tracking_event (
  event_id TEXT PRIMARY KEY, shipment_id TEXT NOT NULL REFERENCES shipment(shipment_id),
  sequence_no INTEGER NOT NULL CHECK(sequence_no > 0),
  event_code TEXT NOT NULL CHECK(event_code IN ('LABEL_CREATED','PACKED','PICKED_UP','IN_TRANSIT','DELIVERED')),
  event_ts TEXT NOT NULL, location TEXT NOT NULL, description TEXT NOT NULL,
  UNIQUE(shipment_id, sequence_no)
);
CREATE TABLE IF NOT EXISTS delivery_promise (
  promise_id TEXT PRIMARY KEY, order_id TEXT NOT NULL UNIQUE REFERENCES orders(order_id),
  promised_delivery_date TEXT, earliest_delivery_date TEXT,
  latest_delivery_date TEXT, calculation_version TEXT NOT NULL,
  reason_code TEXT NOT NULL, calculated_at TEXT NOT NULL, promise_status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_status_event (
  order_event_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(order_id),
  from_status TEXT CHECK(from_status IS NULL OR from_status IN ('CREATED','ALLOCATED','BACKORDERED','CARRIER_REVIEW','READY_TO_SHIP','IN_TRANSIT','DELIVERED','DELIVERED_LATE')),
  to_status TEXT NOT NULL CHECK(to_status IN ('CREATED','ALLOCATED','BACKORDERED','CARRIER_REVIEW','READY_TO_SHIP','IN_TRANSIT','DELIVERED','DELIVERED_LATE')),
  event_ts TEXT NOT NULL, reason TEXT NOT NULL, sequence_no INTEGER NOT NULL,
  UNIQUE(order_id, sequence_no)
);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(order_ts);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(order_status);
CREATE INDEX IF NOT EXISTS idx_shipment_order ON shipment(order_id);
CREATE INDEX IF NOT EXISTS idx_shipment_promise ON shipment(promised_delivery_date);
CREATE INDEX IF NOT EXISTS idx_tracking_shipment ON tracking_event(shipment_id, sequence_no);
CREATE INDEX IF NOT EXISTS idx_shipment_line_by_line ON shipment_line(line_id);
CREATE INDEX IF NOT EXISTS idx_shipment_node_date ON shipment(node_id, ship_date);
CREATE INDEX IF NOT EXISTS idx_order_line_sku ON order_line(sku_id, order_id);
CREATE INDEX IF NOT EXISTS idx_inventory_sku ON inventory(sku_id, node_id);
CREATE INDEX IF NOT EXISTS idx_capacity_date ON warehouse_capacity(capacity_date, node_id);
"""
