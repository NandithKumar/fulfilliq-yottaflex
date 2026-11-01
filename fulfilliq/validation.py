"""Data-quality, referential, lifecycle and reconciliation checks."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any


class ValidationFailure(RuntimeError):
    pass


def validate_database(db_path: str | Path, expected_orders: int | None = None, expected_events: int | None = None) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    checks: list[dict[str, Any]] = []

    def check(name: str, sql: str, expected: Any = 0, comparator: str = "eq", detail: str = "") -> None:
        value = conn.execute(sql).fetchone()[0]
        passed = value == expected if comparator == "eq" else value <= expected if comparator == "lte" else value >= expected
        checks.append({"name": name, "passed": bool(passed), "observed": value, "expected": expected, "detail": detail})

    check("foreign_key_integrity", "SELECT COUNT(*) FROM pragma_foreign_key_check")
    check("duplicate_order_ids", "SELECT COUNT(*) FROM (SELECT order_id FROM orders GROUP BY order_id HAVING COUNT(*) > 1)")
    check("duplicate_line_ids", "SELECT COUNT(*) FROM (SELECT line_id FROM order_line GROUP BY line_id HAVING COUNT(*) > 1)")
    check("duplicate_shipment_ids", "SELECT COUNT(*) FROM (SELECT shipment_id FROM shipment GROUP BY shipment_id HAVING COUNT(*) > 1)")
    check("duplicate_tracking_ids", "SELECT COUNT(*) FROM (SELECT event_id FROM tracking_event GROUP BY event_id HAVING COUNT(*) > 1)")
    check("invalid_line_totals", "SELECT COUNT(*) FROM order_line WHERE ABS(line_total - quantity * unit_price) > 0.011")
    check("invalid_inventory_balance", "SELECT COUNT(*) FROM inventory WHERE available != MAX(0,on_hand-reserved-safety_stock) OR reserved > on_hand")
    check("invalid_capacity_balance", "SELECT COUNT(*) FROM warehouse_capacity WHERE available_units != total_units-reserved_units OR reserved_units > total_units")
    check("shipment_unit_reconciliation", """SELECT COUNT(*) FROM shipment s WHERE s.total_units != (SELECT COALESCE(SUM(sl.quantity),0) FROM shipment_line sl WHERE sl.shipment_id=s.shipment_id)""")
    check("shipment_line_order_consistency", """SELECT COUNT(*) FROM shipment_line sl JOIN shipment s ON s.shipment_id=sl.shipment_id JOIN order_line ol ON ol.line_id=sl.line_id WHERE s.order_id != ol.order_id""")
    check("line_allocation_not_overordered", """SELECT COUNT(*) FROM (SELECT ol.line_id,ol.quantity,COALESCE(SUM(sl.quantity),0) allocated FROM order_line ol LEFT JOIN shipment_line sl ON sl.line_id=ol.line_id GROUP BY ol.line_id HAVING allocated > ol.quantity)""")
    check("inventory_reservation_reconciliation", """SELECT COUNT(*) FROM inventory i
           LEFT JOIN (SELECT s.node_id,ol.sku_id,SUM(sl.quantity) AS allocated
                      FROM shipment_line sl JOIN shipment s ON s.shipment_id=sl.shipment_id
                      JOIN order_line ol ON ol.line_id=sl.line_id GROUP BY s.node_id,ol.sku_id) a
             ON a.node_id=i.node_id AND a.sku_id=i.sku_id
           WHERE i.reserved != COALESCE(a.allocated,0)""")
    check("capacity_reservation_reconciliation", """SELECT COUNT(*) FROM warehouse_capacity c
           LEFT JOIN (SELECT node_id,ship_date,SUM(total_units) AS allocated FROM shipment GROUP BY node_id,ship_date) a
             ON a.node_id=c.node_id AND a.ship_date=c.capacity_date
           WHERE c.reserved_units != COALESCE(a.allocated,0)""")
    check("promise_not_before_order", """SELECT COUNT(*) FROM delivery_promise p JOIN orders o ON o.order_id=p.order_id WHERE p.promise_status!='UNAVAILABLE' AND p.promised_delivery_date < substr(o.order_ts,1,10)""")
    check("promise_latest_child_shipment", """SELECT COUNT(*) FROM delivery_promise p WHERE p.promise_status!='UNAVAILABLE' AND p.promised_delivery_date != (SELECT MAX(s.promised_delivery_date) FROM shipment s WHERE s.order_id=p.order_id)""")
    check("tracking_sequence_chronology", """SELECT COUNT(*) FROM (SELECT shipment_id,sequence_no,event_ts,LAG(event_ts) OVER (PARTITION BY shipment_id ORDER BY sequence_no) prior FROM tracking_event) WHERE prior IS NOT NULL AND event_ts < prior""")
    check("tracking_not_after_snapshot", """SELECT COUNT(*) FROM tracking_event e JOIN shipment s ON s.shipment_id=e.shipment_id JOIN delivery_promise p ON p.order_id=s.order_id WHERE e.event_ts > p.calculated_at""")
    check("dispatch_not_after_snapshot", """SELECT COUNT(*) FROM shipment s JOIN delivery_promise p ON p.order_id=s.order_id WHERE s.dispatch_ts > p.calculated_at""")
    check("pickup_not_before_dispatch", """SELECT COUNT(*) FROM tracking_event e JOIN shipment s ON s.shipment_id=e.shipment_id WHERE e.event_code='PICKED_UP' AND (s.dispatch_ts IS NULL OR e.event_ts < s.dispatch_ts)""")
    check("shipment_dispatch_state_alignment", """SELECT COUNT(*) FROM shipment s WHERE
           (s.status='READY_TO_SHIP' AND (s.dispatch_ts IS NOT NULL OR s.actual_delivery_date IS NOT NULL
             OR NOT EXISTS (SELECT 1 FROM tracking_event e WHERE e.shipment_id=s.shipment_id AND e.event_code='PACKED')
             OR EXISTS (SELECT 1 FROM tracking_event e WHERE e.shipment_id=s.shipment_id AND e.event_code IN ('PICKED_UP','IN_TRANSIT','DELIVERED'))))
           OR (s.status='IN_TRANSIT' AND (s.dispatch_ts IS NULL OR s.actual_delivery_date IS NOT NULL
             OR NOT EXISTS (SELECT 1 FROM tracking_event e WHERE e.shipment_id=s.shipment_id AND e.event_code='PICKED_UP')
             OR EXISTS (SELECT 1 FROM tracking_event e WHERE e.shipment_id=s.shipment_id AND e.event_code='DELIVERED')))
           OR (s.status IN ('DELIVERED','DELIVERED_LATE') AND (s.dispatch_ts IS NULL OR s.actual_delivery_date IS NULL
             OR NOT EXISTS (SELECT 1 FROM tracking_event e WHERE e.shipment_id=s.shipment_id AND e.event_code='PICKED_UP')
             OR NOT EXISTS (SELECT 1 FROM tracking_event e WHERE e.shipment_id=s.shipment_id AND e.event_code='DELIVERED')))""")
    check("order_rollup_all_children", """WITH rollup AS (
             SELECT order_id,COUNT(*) AS shipment_count,
                    SUM(CASE WHEN status IN ('DELIVERED','DELIVERED_LATE') THEN 1 ELSE 0 END) AS delivered_count,
                    SUM(CASE WHEN status IN ('IN_TRANSIT','DELIVERED','DELIVERED_LATE') THEN 1 ELSE 0 END) AS dispatched_count,
                    MAX(actual_delivery_date) AS last_delivery
             FROM shipment GROUP BY order_id
           )
           SELECT COUNT(*) FROM orders o JOIN rollup r ON r.order_id=o.order_id
           LEFT JOIN delivery_promise p ON p.order_id=o.order_id
           WHERE (r.delivered_count=r.shipment_count AND o.order_status != CASE WHEN r.last_delivery>p.promised_delivery_date THEN 'DELIVERED_LATE' ELSE 'DELIVERED' END)
              OR (r.delivered_count<r.shipment_count AND r.dispatched_count>0 AND o.order_status!='IN_TRANSIT')
              OR (r.delivered_count<r.shipment_count AND r.dispatched_count=0 AND o.order_status!='READY_TO_SHIP')""")
    check("order_event_final_state", """SELECT COUNT(*) FROM orders o WHERE o.order_status !=
           (SELECT e.to_status FROM order_status_event e WHERE e.order_id=o.order_id ORDER BY e.sequence_no DESC LIMIT 1)""")
    check("order_event_timestamp_chronology", """SELECT COUNT(*) FROM (SELECT order_id,sequence_no,event_ts,
           LAG(event_ts) OVER (PARTITION BY order_id ORDER BY sequence_no) prior FROM order_status_event)
           WHERE prior IS NOT NULL AND event_ts < prior""")
    check("backorder_has_no_shipment", """SELECT COUNT(*) FROM orders o WHERE o.order_status IN ('BACKORDERED','CARRIER_REVIEW') AND EXISTS (SELECT 1 FROM shipment s WHERE s.order_id=o.order_id)""")
    check("missing_order_promise", "SELECT COUNT(*) FROM orders o LEFT JOIN delivery_promise p ON p.order_id=o.order_id WHERE p.promise_id IS NULL")
    check("tracking_event_target", "SELECT COUNT(*) FROM tracking_event", expected_events if expected_events is not None else 2 * (expected_orders or conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]))
    check("order_target", "SELECT COUNT(*) FROM orders", expected_orders, "eq") if expected_orders is not None else None
    check("unsupported_carrier_used", """SELECT COUNT(*) FROM shipment s JOIN carrier_service_zone z ON z.carrier_id=s.carrier_id AND z.service_level_id=s.service_level_id JOIN orders o ON o.order_id=s.order_id AND z.zone=o.destination_zone WHERE z.supported=0""")
    check("negative_quantities", "SELECT COUNT(*) FROM order_line WHERE quantity<=0")
    check("duplicate_tracking_sequence", "SELECT COUNT(*) FROM (SELECT shipment_id,sequence_no FROM tracking_event GROUP BY shipment_id,sequence_no HAVING COUNT(*)>1)")
    conn.commit()
    counts = {row["name"]: row["n"] for row in conn.execute("""SELECT 'orders' name,COUNT(*) n FROM orders UNION ALL SELECT 'order_lines',COUNT(*) FROM order_line UNION ALL SELECT 'nodes',COUNT(*) FROM fulfillment_node UNION ALL SELECT 'carriers',COUNT(*) FROM carrier UNION ALL SELECT 'skus',COUNT(*) FROM sku UNION ALL SELECT 'shipments',COUNT(*) FROM shipment UNION ALL SELECT 'tracking_events',COUNT(*) FROM tracking_event UNION ALL SELECT 'delivery_promises',COUNT(*) FROM delivery_promise UNION ALL SELECT 'split_orders',COUNT(*) FROM (SELECT order_id FROM shipment GROUP BY order_id HAVING COUNT(*)>1) UNION ALL SELECT 'backorders',COUNT(*) FROM orders WHERE order_status IN ('BACKORDERED','CARRIER_REVIEW')""")}
    status = dict(conn.execute("SELECT order_status,COUNT(*) FROM orders GROUP BY order_status").fetchall())
    conn.close()
    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "check_count": len(checks), "passed_checks": sum(1 for c in checks if c["passed"]),
            "failed_checks": [c for c in checks if not c["passed"]], "checks": checks, "counts": counts, "order_status": status}


def validate_ground_truth(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    expected = {"PROMISE_BEFORE_ORDER", "ALLOCATION_EXCEEDS_STOCK", "UNSUPPORTED_CARRIER_SERVICE_ZONE", "DELIVERED_BEFORE_DISPATCH", "SPLIT_STATUS_NOT_ROLLED_UP"}
    observed = {x["issue_type"] for x in payload.get("cases", [])}
    return {"passed": expected == observed and len(payload.get("cases", [])) == 5,
            "expected_cases": sorted(expected), "observed_cases": sorted(observed), "case_count": len(payload.get("cases", []))}


def render_summary(result: dict[str, Any]) -> str:
    lines = [f"FULFILLIQ VALIDATION: {'PASS' if result['passed'] else 'FAIL'}",
             f"Checks: {result['passed_checks']}/{result['check_count']} passed", "",
             "DATA COUNTS"]
    lines.extend(f"  {key:22s} {value:,}" for key, value in result["counts"].items())
    lines.extend(["", "ORDER STATUS"])
    lines.extend(f"  {key:22s} {value:,}" for key, value in result["order_status"].items())
    if result["failed_checks"]:
        lines.extend(["", "FAILED CHECKS"])
        lines.extend(f"  - {x['name']}: observed {x['observed']}, expected {x['expected']}" for x in result["failed_checks"])
    return "\n".join(lines)
