"""Zero-dependency HTTP application for the FulfillIQ operations console."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import date, datetime, time, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import ROOT, SAMPLE_DIR, GENERATED_DIR
from .validation import validate_database, validate_ground_truth
from .util import add_business_days

DB_PATH = Path(os.getenv("FULFILLIQ_DB", str((GENERATED_DIR / "fulfilliq.db") if (GENERATED_DIR / "fulfilliq.db").exists() else (SAMPLE_DIR / "fulfilliq.db"))))
WEB_DIR = ROOT / "web"


def db():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}. Run the generator first.")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def rows(conn, sql, args=()):
    return [dict(x) for x in conn.execute(sql, args).fetchall()]


def summary_payload():
    with db() as conn:
        counts = {"orders": conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
                  "shipments": conn.execute("SELECT COUNT(*) FROM shipment").fetchone()[0],
                  "events": conn.execute("SELECT COUNT(*) FROM tracking_event").fetchone()[0],
                  "nodes": conn.execute("SELECT COUNT(*) FROM fulfillment_node").fetchone()[0],
                  "carriers": conn.execute("SELECT COUNT(*) FROM carrier").fetchone()[0],
                  "order_lines": conn.execute("SELECT COUNT(*) FROM order_line").fetchone()[0]}
        status = rows(conn, "SELECT order_status AS label,COUNT(*) AS value FROM orders GROUP BY order_status ORDER BY value DESC")
        daily = rows(conn, """SELECT substr(order_ts,1,10) AS day,COUNT(*) AS orders,
                      SUM(CASE WHEN order_status IN ('DELIVERED','DELIVERED_LATE') THEN 1 ELSE 0 END) AS delivered
                      FROM orders GROUP BY substr(order_ts,1,10) ORDER BY day""")
        node_health = rows(conn, """WITH capacity AS (
                          SELECT node_id,SUM(total_units) AS total_units,SUM(reserved_units) AS reserved_units
                          FROM warehouse_capacity GROUP BY node_id
                      ), shipment_counts AS (
                          SELECT node_id,COUNT(*) AS shipment_count FROM shipment GROUP BY node_id
                      )
                      SELECT n.node_id,n.name,n.city,n.zone,
                      COALESCE(c.total_units,0) AS capacity,
                      COALESCE(c.reserved_units,0) AS reserved,
                      ROUND(100.0*COALESCE(c.reserved_units,0)/NULLIF(c.total_units,0),1) AS utilization,
                      COALESCE(s.shipment_count,0) AS shipments
                      FROM fulfillment_node n LEFT JOIN capacity c ON c.node_id=n.node_id
                      LEFT JOIN shipment_counts s ON s.node_id=n.node_id ORDER BY utilization DESC""")
        late = conn.execute("SELECT COUNT(*) FROM orders WHERE order_status='DELIVERED_LATE'").fetchone()[0]
        on_time = conn.execute("SELECT COUNT(*) FROM delivery_promise WHERE promise_status='ON_TIME'").fetchone()[0]
        completed = conn.execute("SELECT COUNT(*) FROM delivery_promise WHERE promise_status IN ('ON_TIME','LATE')").fetchone()[0]
        unfulfilled = conn.execute("SELECT COUNT(*) FROM orders WHERE order_status IN ('BACKORDERED','CARRIER_REVIEW')").fetchone()[0]
        split_orders = conn.execute("SELECT COUNT(*) FROM (SELECT order_id FROM shipment GROUP BY order_id HAVING COUNT(*)>1)").fetchone()[0]
        total_units = conn.execute("SELECT COALESCE(SUM(total_units),0) FROM shipment").fetchone()[0]
        exception_rows = rows(conn, """SELECT o.order_id,o.destination_city,o.order_status,o.issue_type,o.order_ts
                                  FROM orders o WHERE o.order_status IN ('BACKORDERED','CARRIER_REVIEW','DELIVERED_LATE')
                                  ORDER BY CASE o.order_status WHEN 'BACKORDERED' THEN 0 WHEN 'CARRIER_REVIEW' THEN 1 ELSE 2 END,o.order_ts DESC LIMIT 12""")
        carriers = rows(conn, """SELECT c.name,c.on_time_rate,COUNT(s.shipment_id) shipments,
                            SUM(CASE WHEN s.status='DELIVERED_LATE' THEN 1 ELSE 0 END) late
                            FROM carrier c LEFT JOIN shipment s ON s.carrier_id=c.carrier_id GROUP BY c.carrier_id ORDER BY shipments DESC""")
        snapshot = rows(conn, "SELECT MAX(updated_at) AS snapshot FROM inventory")[0]["snapshot"]
    return {"counts": counts, "status": status, "daily": daily, "node_health": node_health,
            "metrics": {"on_time_pct": round(on_time / completed * 100, 1) if completed else 0,
                        "late_orders": late, "unfulfilled_pct": round(unfulfilled / counts["orders"] * 100, 1) if counts["orders"] else 0,
                        "split_orders": split_orders, "split_pct": round(split_orders / counts["orders"] * 100, 1) if counts["orders"] else 0,
                        "units_allocated": total_units, "completed_promises": completed},
            "exceptions": exception_rows, "carriers": carriers, "snapshot_at": snapshot, "database": DB_PATH.name}


def list_orders(params):
    q = (params.get("q") or [""])[0].strip()
    status = (params.get("status") or [""])[0].strip()
    page = max(1, int((params.get("page") or ["1"])[0]))
    page_size = min(100, max(10, int((params.get("page_size") or ["25"])[0])))
    clauses, args = [], []
    if q:
        clauses.append("(o.order_id LIKE ? OR o.destination_city LIKE ? OR o.customer_id LIKE ?)")
        args.extend([f"%{q}%"] * 3)
    if status:
        clauses.append("o.order_status=?")
        args.append(status)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM orders o" + where, args).fetchone()[0]
        result = rows(conn, f"""SELECT o.order_id,o.order_ts,o.destination_city,o.destination_zone,o.priority,o.order_status,o.issue_type,
                    p.promised_delivery_date,p.promise_status,
                    (SELECT COUNT(*) FROM shipment s WHERE s.order_id=o.order_id) AS shipment_count,
                    (SELECT COALESCE(SUM(ol.quantity),0) FROM order_line ol WHERE ol.order_id=o.order_id) AS units_ordered
                    FROM orders o LEFT JOIN delivery_promise p ON p.order_id=o.order_id{where}
                    ORDER BY o.order_ts DESC LIMIT ? OFFSET ?""", args + [page_size, (page - 1) * page_size])
    return {"items": result, "total": total, "page": page, "page_size": page_size}


def order_detail(order_id: str):
    with db() as conn:
        order = rows(conn, """SELECT o.*,p.promised_delivery_date,p.earliest_delivery_date,p.latest_delivery_date,p.promise_status,p.reason_code,p.calculation_version
                         FROM orders o LEFT JOIN delivery_promise p ON p.order_id=o.order_id WHERE o.order_id=?""", (order_id,))
        if not order:
            return None
        lines = rows(conn, """SELECT ol.*,sku.name AS sku_name,sku.category FROM order_line ol JOIN sku ON sku.sku_id=ol.sku_id WHERE ol.order_id=? ORDER BY ol.line_id""", (order_id,))
        shipments = rows(conn, """SELECT s.*,n.name AS node_name,n.city AS node_city,c.name AS carrier_name,sv.name AS service_name
                              FROM shipment s JOIN fulfillment_node n ON n.node_id=s.node_id JOIN carrier c ON c.carrier_id=s.carrier_id
                              JOIN service_level sv ON sv.service_level_id=s.service_level_id WHERE s.order_id=? ORDER BY s.shipment_id""", (order_id,))
        events = rows(conn, """SELECT e.*,s.order_id FROM tracking_event e JOIN shipment s ON s.shipment_id=e.shipment_id
                           WHERE s.order_id=? ORDER BY e.event_ts,e.sequence_no""", (order_id,))
        allocation = rows(conn, """SELECT sl.shipment_id,sl.line_id,sl.quantity,ol.sku_id,sku.name AS sku_name FROM shipment_line sl
                               JOIN shipment s ON s.shipment_id=sl.shipment_id JOIN order_line ol ON ol.line_id=sl.line_id
                               JOIN sku ON sku.sku_id=ol.sku_id WHERE s.order_id=? ORDER BY sl.shipment_id,sl.line_id""", (order_id,))
    return {"order": order[0], "lines": lines, "shipments": shipments, "events": events, "allocations": allocation}


def _next_operational_day(conn, carrier_id: str, start: date):
    cursor = start
    for _ in range(15):
        row = conn.execute("SELECT is_operational FROM carrier_calendar WHERE carrier_id=? AND service_date=?", (carrier_id, cursor.isoformat())).fetchone()
        if row and row[0]:
            return cursor
        cursor += timedelta(days=1)
    return cursor


def preview_decision(payload):
    zone = str(payload.get("zone", "SOUTH")).upper()
    service_name = str(payload.get("service_level", "STANDARD")).upper()
    order_time_text = payload.get("order_time") or datetime.now().astimezone().isoformat(timespec="minutes")
    try:
        order_ts = datetime.fromisoformat(order_time_text)
    except ValueError:
        raise ValueError("order_time must be ISO-8601")
    line_inputs = payload.get("lines") or []
    if zone not in {"NORTH", "SOUTH", "EAST", "WEST", "CENTRAL"}:
        raise ValueError("zone must be NORTH, SOUTH, EAST, WEST or CENTRAL")
    if not line_inputs or len(line_inputs) > 10:
        raise ValueError("Provide between 1 and 10 order lines")
    with db() as conn:
        service = conn.execute("SELECT * FROM service_level WHERE name=?", (service_name,)).fetchone()
        if not service:
            raise ValueError("Unknown service level")
        clean_lines = []
        for item in line_inputs:
            sku_id = str(item.get("sku_id", ""))
            qty = int(item.get("quantity", 0))
            sku = conn.execute("SELECT sku_id,name,unit_price FROM sku WHERE sku_id=? AND is_active=1", (sku_id,)).fetchone()
            if not sku or qty < 1 or qty > 100:
                raise ValueError(f"Invalid SKU or quantity: {sku_id}")
            clean_lines.append({"sku_id": sku_id, "sku_name": sku["name"], "quantity": qty, "unit_price": sku["unit_price"]})
        carriers = rows(conn, """SELECT c.*,z.avg_transit_days,z.surcharge FROM carrier c JOIN carrier_service_zone z ON z.carrier_id=c.carrier_id
                               WHERE z.service_level_id=? AND z.zone=? AND z.supported=1""", (service["service_level_id"], zone))
        if not carriers:
            return {"decision": "NO_SUPPORTED_CARRIER", "message": "No carrier supports this service and destination zone.", "candidates": []}
        holiday_dates = {date.fromisoformat(x[0]) for x in conn.execute("SELECT holiday_date FROM public_holiday WHERE zone='ALL' OR zone=?", (zone,)).fetchall()}
        nodes = rows(conn, "SELECT * FROM fulfillment_node WHERE is_active=1")
        candidates = []
        for node in nodes:
            inv = {}
            enough_stock = True
            for line in clean_lines:
                item = conn.execute("SELECT available FROM inventory WHERE node_id=? AND sku_id=?", (node["node_id"], line["sku_id"])).fetchone()
                available = item[0] if item else 0
                inv[line["sku_id"]] = available
                if available < line["quantity"]:
                    enough_stock = False
            for carrier in carriers:
                cutoff = time.fromisoformat(carrier["cutoff_time"])
                dispatch_start = order_ts.date() if order_ts.time() <= cutoff else order_ts.date() + timedelta(days=1)
                dispatch = _next_operational_day(conn, carrier["carrier_id"], dispatch_start)
                cap = conn.execute("SELECT available_units,total_units FROM warehouse_capacity WHERE node_id=? AND capacity_date=?", (node["node_id"], dispatch.isoformat())).fetchone()
                available_capacity = cap[0] if cap else 0
                total_capacity = cap[1] if cap else 1
                required = sum(x["quantity"] for x in clean_lines)
                capacity_ok = available_capacity >= required
                transit = round(carrier["avg_transit_days"])
                carrier_operating_days = {int(x) for x in carrier["operating_days"].split(",")}
                earliest = add_business_days(dispatch, service["min_transit_days"], holiday_dates, carrier_operating_days)
                latest = add_business_days(dispatch, service["max_transit_days"], holiday_dates, carrier_operating_days)
                score = carrier["avg_transit_days"] * 10 + (carrier["base_cost"] + carrier["surcharge"]) * .08 + (2 if node["zone"] != zone else 0) - (available_capacity / max(1, total_capacity)) * 3 - carrier["on_time_rate"] * 4
                candidates.append({"node_id": node["node_id"], "node_name": node["name"], "city": node["city"], "node_zone": node["zone"],
                                   "carrier_id": carrier["carrier_id"], "carrier": carrier["name"], "cutoff": carrier["cutoff_time"],
                                   "dispatch_date": dispatch.isoformat(), "earliest_promise": earliest.isoformat(), "latest_promise": latest.isoformat(),
                                   "transit_days_estimate": transit, "available_capacity": available_capacity, "required_capacity": required,
                                   "inventory_available": inv, "inventory_ok": enough_stock, "capacity_ok": capacity_ok,
                                   "on_time_rate": carrier["on_time_rate"], "estimated_cost_inr": round(carrier["base_cost"] + carrier["surcharge"], 2),
                                   "score": round(score, 3), "feasible": enough_stock and capacity_ok})
        candidates.sort(key=lambda x: (not x["feasible"], x["score"], x["node_id"], x["carrier_id"]))
        feasible = [x for x in candidates if x["feasible"]]
        if feasible:
            chosen = feasible[0]
            return {"decision": "ALLOCATE_SINGLE_NODE", "message": "Best feasible node/carrier combination selected using inventory, daily capacity, cutoff calendar, service support, transit and cost.",
                    "chosen": chosen, "candidates": candidates[:12], "lines": clean_lines,
                    "explanation": ["All requested SKU quantities are available at the selected node.",
                                    "Daily warehouse capacity covers the complete order.",
                                    "Carrier supports the requested service level and destination zone.",
                                    "Promise window accounts for cutoff and operational calendar."]}
        # If no single node can fulfil the basket, show the best per-line node options.
        split_plan = []
        # A split plan uses local ledgers so two individually feasible lines cannot
        # overbook the same node/date or consume the same SKU stock twice.
        remaining_stock: dict[tuple[str, str], int] = {}
        remaining_capacity: dict[tuple[str, str], int] = {}
        for candidate in candidates:
            for sku_id, available in candidate["inventory_available"].items():
                remaining_stock[(candidate["node_id"], sku_id)] = available
            remaining_capacity[(candidate["node_id"], candidate["dispatch_date"])] = candidate["available_capacity"]

        for line in clean_lines:
            options = [x for x in candidates
                       if remaining_stock.get((x["node_id"], line["sku_id"]), 0) >= line["quantity"]
                       and remaining_capacity.get((x["node_id"], x["dispatch_date"]), 0) >= line["quantity"]]
            if not options:
                break
            choice = options[0]
            stock_key = (choice["node_id"], line["sku_id"])
            capacity_key = (choice["node_id"], choice["dispatch_date"])
            remaining_stock[stock_key] -= line["quantity"]
            remaining_capacity[capacity_key] -= line["quantity"]
            split_plan.append({"sku_id": line["sku_id"], "sku_name": line["sku_name"], "quantity": line["quantity"],
                               "node_id": choice["node_id"], "node_name": choice["node_name"], "carrier": choice["carrier"],
                               "dispatch_date": choice["dispatch_date"], "latest_promise": choice["latest_promise"],
                               "remaining_node_day_capacity": remaining_capacity[capacity_key]})
        if len(split_plan) == len(clean_lines):
            return {"decision": "ALLOCATE_SPLIT", "message": "No single node can cover the full basket; the line-level split fits available stock and cumulative node/day capacity.",
                    "split_plan": split_plan, "order_promise": max(x["latest_promise"] for x in split_plan),
                    "candidates": candidates[:12], "lines": clean_lines,
                    "explanation": ["Each line has a feasible stock and capacity candidate.",
                                    "A local reservation ledger checks cumulative SKU stock and node/date capacity across all split lines.",
                                    "The order promise is the latest child-shipment promise."]}
        reason = "INVENTORY_UNAVAILABLE" if not any(x["inventory_ok"] for x in candidates) else "CAPACITY_LIMIT_OR_CARRIER_CALENDAR"
        return {"decision": "ESCALATE", "message": "No feasible single-node or complete split allocation was found. Do not over-promise; create an exception for operations review.",
                "reason": reason, "candidates": candidates[:12], "lines": clean_lines,
                "explanation": ["No candidate covers all line quantities and constraints.", "No inventory or capacity is reserved by this preview endpoint."]}


class Handler(BaseHTTPRequestHandler):
    server_version = "FulfillIQ/1.0"

    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/" or path == "/index.html":
            file_path = WEB_DIR / "index.html"
            return self._send(200, file_path.read_text(encoding="utf-8"), "text/html; charset=utf-8")
        if path.startswith("/assets/"):
            asset = WEB_DIR / path.removeprefix("/assets/")
            if not asset.exists() or not asset.is_file():
                return self._send(404, {"error": "asset not found"})
            mime = "text/css; charset=utf-8" if asset.suffix == ".css" else "application/javascript; charset=utf-8"
            return self._send(200, asset.read_text(encoding="utf-8"), mime)
        try:
            if path == "/api/health":
                return self._send(200, {"ok": True, "database": DB_PATH.name})
            if path == "/api/summary":
                return self._send(200, summary_payload())
            if path == "/api/orders":
                return self._send(200, list_orders(parse_qs(parsed.query)))
            if path.startswith("/api/orders/"):
                detail = order_detail(path.split("/")[-1])
                return self._send(200 if detail else 404, detail or {"error": "order not found"})
            if path == "/api/validation":
                result = validate_database(DB_PATH)
                gt_path = DB_PATH.parent / "ground_truth.json"
                result["ground_truth"] = validate_ground_truth(gt_path) if gt_path.exists() else None
                return self._send(200, result)
            if path == "/api/skus":
                with db() as conn:
                    return self._send(200, rows(conn, """SELECT sku.sku_id,sku.name,sku.category,sku.unit_price,
                                  COALESCE(SUM(inventory.available),0) AS available_total
                                  FROM sku LEFT JOIN inventory ON inventory.sku_id=sku.sku_id
                                  WHERE sku.is_active=1 GROUP BY sku.sku_id
                                  ORDER BY available_total DESC,sku.sku_id LIMIT 100"""))
        except Exception as exc:
            return self._send(500, {"error": str(exc)})
        return self._send(404, {"error": "route not found"})

    def do_POST(self):
        if self.path != "/api/decision":
            return self._send(404, {"error": "route not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 25000:
                return self._send(413, {"error": "request too large"})
            payload = json.loads(self.rfile.read(length) or b"{}")
            return self._send(200, preview_decision(payload))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self._send(400, {"error": str(exc)})
        except Exception as exc:
            return self._send(500, {"error": str(exc)})

    def log_message(self, fmt, *args):
        if os.getenv("FULFILLIQ_ACCESS_LOG", "0") == "1":
            super().log_message(fmt, *args)


def main():
    host = os.getenv("FULFILLIQ_HOST", "127.0.0.1")
    port = int(os.getenv("FULFILLIQ_PORT", "8765"))
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}. Generate data with: python -m fulfilliq.cli generate --orders 500")
        return 2
    server = ThreadingHTTPServer((host, port), Handler)
    print("\n  F U L F I L L I Q   //   NETWORK CONTROL TOWER")
    print(f"  Console : http://{host}:{port}")
    print(f"  Database: {DB_PATH}")
    print("  Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down FulfillIQ...")
    finally:
        server.server_close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
