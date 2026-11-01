"""Deterministic synthetic fulfillment network generator.

The generator builds clean baseline records first. Deliberate bad-data scenarios are
written to a separate ground-truth fixture and never mixed into baseline inputs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import sqlite3
import sys
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from .config import ENGINE_VERSION, GenerationConfig, SNAPSHOT_AT
from .schema import SCHEMA_SQL
from .util import add_business_days, canonical_json, iso, stable_int

ZONES = ["NORTH", "SOUTH", "EAST", "WEST", "CENTRAL"]
ZONE_CITIES = {
    "NORTH": ["Delhi", "Jaipur", "Lucknow", "Chandigarh"],
    "SOUTH": ["Hyderabad", "Bengaluru", "Chennai", "Kochi"],
    "EAST": ["Kolkata", "Bhubaneswar", "Patna", "Guwahati"],
    "WEST": ["Mumbai", "Pune", "Ahmedabad", "Surat"],
    "CENTRAL": ["Bhopal", "Indore", "Nagpur", "Raipur"],
}
NODE_CITIES = [
    ("Hyderabad", "TELANGANA", "SOUTH", 17.385, 78.4867),
    ("Bengaluru", "KARNATAKA", "SOUTH", 12.9716, 77.5946),
    ("Chennai", "TAMIL_NADU", "SOUTH", 13.0827, 80.2707),
    ("Kochi", "KERALA", "SOUTH", 9.9312, 76.2673),
    ("Delhi", "DELHI", "NORTH", 28.6139, 77.2090),
    ("Jaipur", "RAJASTHAN", "NORTH", 26.9124, 75.7873),
    ("Lucknow", "UTTAR_PRADESH", "NORTH", 26.8467, 80.9462),
    ("Chandigarh", "CHANDIGARH", "NORTH", 30.7333, 76.7794),
    ("Mumbai", "MAHARASHTRA", "WEST", 19.0760, 72.8777),
    ("Pune", "MAHARASHTRA", "WEST", 18.5204, 73.8567),
    ("Ahmedabad", "GUJARAT", "WEST", 23.0225, 72.5714),
    ("Surat", "GUJARAT", "WEST", 21.1702, 72.8311),
    ("Kolkata", "WEST_BENGAL", "EAST", 22.5726, 88.3639),
    ("Bhubaneswar", "ODISHA", "EAST", 20.2961, 85.8245),
    ("Patna", "BIHAR", "EAST", 25.5941, 85.1376),
    ("Guwahati", "ASSAM", "EAST", 26.1445, 91.7362),
    ("Bhopal", "MADHYA_PRADESH", "CENTRAL", 23.2599, 77.4126),
    ("Indore", "MADHYA_PRADESH", "CENTRAL", 22.7196, 75.8577),
    ("Nagpur", "MAHARASHTRA", "CENTRAL", 21.1458, 79.0882),
    ("Raipur", "CHHATTISGARH", "CENTRAL", 21.2514, 81.6296),
]
SERVICE_LEVELS = [
    {"service_level_id": "SVC-STD", "name": "STANDARD", "min_transit_days": 3, "max_transit_days": 5, "priority_rank": 3},
    {"service_level_id": "SVC-EXP", "name": "EXPRESS", "min_transit_days": 1, "max_transit_days": 2, "priority_rank": 2},
    {"service_level_id": "SVC-ECO", "name": "ECONOMY", "min_transit_days": 4, "max_transit_days": 7, "priority_rank": 4},
    {"service_level_id": "SVC-PRI", "name": "PRIORITY", "min_transit_days": 1, "max_transit_days": 1, "priority_rank": 1},
]
CATEGORIES = ["ELECTRONICS", "HOME", "APPAREL", "BEAUTY", "SPORTS", "BOOKS", "GROCERY"]
CARRIER_NAMES = ["AsterShip", "BlueDart Synthetic", "ParcelNova", "RapidRoute", "NorthStar Logistics", "SwiftCart", "Orbit Express", "Pioneer Freight", "MetroParcel", "CloudLane"]


def _insert_many(conn: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0].keys())
    placeholders = ",".join("?" for _ in columns)
    sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
    conn.executemany(sql, ([row.get(c) for c in columns] for row in rows))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _carrier_dispatch_date(order_ts: datetime, carrier: dict[str, Any], calendar: dict[tuple[str, date], bool]) -> date:
    cutoff = time.fromisoformat(carrier["cutoff_time"])
    candidate = order_ts.date()
    operating_days = {int(x) for x in carrier["operating_days"].split(",")}
    if order_ts.time() > cutoff or candidate.weekday() not in operating_days or not calendar.get((carrier["carrier_id"], candidate), False):
        candidate += timedelta(days=1)
        while candidate.weekday() not in operating_days or not calendar.get((carrier["carrier_id"], candidate), False):
            candidate += timedelta(days=1)
    return candidate


def _service_options(carriers: list[dict[str, Any]], routes: dict[tuple[str, str, str], dict[str, Any]], service_id: str, zone: str):
    options = []
    for carrier in carriers:
        route = routes.get((carrier["carrier_id"], service_id, zone))
        if route and route["supported"]:
            score = carrier["base_cost"] + route["surcharge"] + route["avg_transit_days"] * 1.7 - carrier["on_time_rate"] * 4
            options.append((score, carrier, route))
    return sorted(options, key=lambda x: (x[0], x[1]["carrier_id"]))


def _promise_dates(dispatch_date: date, service: dict[str, Any], carrier: dict[str, Any], holidays: set[date]) -> tuple[date, date, date]:
    days = {int(x) for x in carrier["operating_days"].split(",")}
    earliest = add_business_days(dispatch_date, service["min_transit_days"], holidays, days)
    latest = add_business_days(dispatch_date, service["max_transit_days"], holidays, days)
    return earliest, latest, latest


def _make_master(config: GenerationConfig, rng: random.Random):
    skus = []
    unavailable = max(5, min(15, config.skus // 30))
    for i in range(1, config.skus + 1):
        skus.append({
            "sku_id": f"SKU-{i:06d}", "name": f"{rng.choice(CATEGORIES).title()} Item {i:04d}",
            "category": CATEGORIES[(i - 1) % len(CATEGORIES)],
            "unit_weight_kg": round(rng.uniform(0.08, 12.0), 3),
            "unit_price": round(rng.uniform(149, 24999), 2), "is_active": 1,
        })
    nodes = []
    for i in range(config.nodes):
        city, state, zone, lat, lon = NODE_CITIES[i % len(NODE_CITIES)]
        nodes.append({
            "node_id": f"FUL-2026-{i + 1:06d}", "name": f"{city} {('FC' if i % 3 == 0 else 'Hub' if i % 3 == 1 else 'Store')} {i + 1:02d}",
            "city": city, "state": state, "zone": zone, "node_type": ["FULFILLMENT_CENTER", "DARK_STORE", "STORE"][i % 3],
            "latitude": lat, "longitude": lon, "is_active": 1,
        })
    carriers = []
    for i in range(config.carriers):
        carriers.append({
            "carrier_id": f"CAR-{i + 1:03d}", "name": CARRIER_NAMES[i % len(CARRIER_NAMES)],
            "cutoff_time": f"{15 + (i % 4):02d}:{'00' if i % 2 == 0 else '30'}",
            "operating_days": "0,1,2,3,4,5", "on_time_rate": round(0.88 + (i % 6) * 0.018, 3),
            "base_cost": round(36 + (i % 5) * 8.5, 2), "handling_hours": 2 + i % 5,
        })
    services = [dict(x) for x in SERVICE_LEVELS]
    return skus, nodes, carriers, services, unavailable


def generate(config: GenerationConfig) -> dict[str, Any]:
    """Generate a complete reproducible dataset and return a concise run summary."""
    if config.orders < 1 or config.nodes < 2 or config.carriers < 1 or config.skus < 10:
        raise ValueError("orders>=1, nodes>=2, carriers>=1 and skus>=10 are required")
    if config.tracking_events is not None and config.tracking_events != config.orders * 2:
        raise ValueError("For this dataset contract, tracking_events must equal exactly 2 × orders.")
    output = Path(config.output)
    output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(config.seed)
    skus, nodes, carriers, services, unavailable_count = _make_master(config, rng)
    service_by_id = {x["service_level_id"]: x for x in services}
    sku_by_id = {x["sku_id"]: x for x in skus}

    holidays = {
        date(2026, 10, 2): "Synthetic carrier closure: Founders Day",
        date(2026, 10, 20): "Synthetic carrier closure: Regional Festival",
        date(2026, 10, 31): "Synthetic carrier closure: Network Maintenance",
    }
    public_holidays = [{"holiday_date": d.isoformat(), "holiday_name": name, "zone": "ALL"} for d, name in sorted(holidays.items())]
    calendar_rows, calendar_map = [], {}
    start_day = config.snapshot_at.date() - timedelta(days=48)
    end_day = config.snapshot_at.date() + timedelta(days=14)
    for carrier in carriers:
        operating_days = {int(x) for x in carrier["operating_days"].split(",")}
        for day in _daterange(start_day, end_day):
            operational = day.weekday() in operating_days and day not in holidays
            calendar_map[(carrier["carrier_id"], day)] = operational
            calendar_rows.append({"carrier_id": carrier["carrier_id"], "service_date": day.isoformat(), "is_operational": int(operational), "holiday_name": holidays.get(day)})

    routes = {}
    route_rows = []
    for carrier_index, carrier in enumerate(carriers):
        for service_index, service in enumerate(services):
            for zone_index, zone in enumerate(ZONES):
                supported = (carrier_index < min(2, len(carriers))) or ((carrier_index * 7 + service_index * 3 + zone_index * 5 + config.seed) % 5 != 0)
                avg = (service["min_transit_days"] + service["max_transit_days"]) / 2 + (zone_index % 3) * 0.25 + (carrier_index % 3) * 0.15
                route = {"carrier_id": carrier["carrier_id"], "service_level_id": service["service_level_id"], "zone": zone,
                         "avg_transit_days": round(avg, 2), "supported": int(supported), "surcharge": round((zone_index % 3) * 5.5, 2)}
                routes[(carrier["carrier_id"], service["service_level_id"], zone)] = route
                route_rows.append(route)
    service_options_cache = {(service["service_level_id"], zone): _service_options(carriers, routes, service["service_level_id"], zone)
                             for service in services for zone in ZONES}
    carrier_by_id = {x["carrier_id"]: x for x in carriers}
    node_by_id = {x["node_id"]: x for x in nodes}
    available_sku_ids = [f"SKU-{x:06d}" for x in range(unavailable_count + 1, config.skus + 1)]
    holiday_set = set(holidays)

    # Inventory is deliberately generous in the clean baseline; a small SKU family is
    # globally unavailable to create a realistic, explainable backorder population.
    inventory_rows = []
    stock_remaining: dict[tuple[str, str], int] = {}
    stock_reserved: dict[tuple[str, str], int] = defaultdict(int)
    unavailable_skus = {f"SKU-{i:06d}" for i in range(1, unavailable_count + 1)}
    for node_index, node in enumerate(nodes):
        for sku in skus:
            on_hand = 0 if sku["sku_id"] in unavailable_skus else rng.randint(110, 210)
            safety = 0 if on_hand == 0 else rng.randint(5, 12)
            stock_remaining[(node["node_id"], sku["sku_id"])] = max(0, on_hand - safety)
            inventory_rows.append({
                "inventory_id": f"INV-{node_index + 1:03d}-{int(sku['sku_id'].split('-')[1]):06d}",
                "node_id": node["node_id"], "sku_id": sku["sku_id"], "on_hand": on_hand,
                "reserved": 0, "safety_stock": safety, "available": max(0, on_hand - safety),
                "updated_at": config.snapshot_at.isoformat(),
            })

    # Daily capacity makes the constraint observable while preserving enough network headroom.
    capacity_rows = []
    capacity_remaining: dict[tuple[str, date], int] = {}
    capacity_initial: dict[tuple[str, date], int] = {}
    for node_index, node in enumerate(nodes):
        for day in _daterange(start_day, end_day):
            stress = (day.day + node_index * 3 + config.seed) % 11 == 0
            total = rng.randint(170, 270) if stress else rng.randint(330, 520)
            key = (node["node_id"], day)
            capacity_remaining[key] = total
            capacity_initial[key] = total
            capacity_rows.append({"capacity_id": f"CAP-{node_index + 1:03d}-{day.strftime('%Y%m%d')}", "node_id": node["node_id"],
                                  "capacity_date": day.isoformat(), "total_units": total, "reserved_units": 0, "available_units": total})

    node_index_by_id = {x["node_id"]: i for i, x in enumerate(nodes)}
    # Build orders first so the required parent IDs exist before any dependent rows.
    order_rows, line_rows = [], []
    order_meta: list[dict[str, Any]] = []
    split_count = max(1, int(round(config.orders * 0.03))) if config.orders >= 20 else 0
    no_ship_count = split_count
    indices = list(range(config.orders))
    rng.shuffle(indices)
    split_indices = set(indices[:split_count])
    backorder_indices = set(indices[split_count:split_count + no_ship_count])
    start_ts = config.snapshot_at - timedelta(days=45)
    total_lines = 0
    for index in range(config.orders):
        order_number = index + 1
        order_id = f"ORD-2026-{order_number:06d}"
        # A reproducible rolling demand curve with a mild weekend skew.
        seconds = rng.randint(0, 45 * 24 * 3600 - 1)
        order_ts = start_ts + timedelta(seconds=seconds)
        dest_zone = rng.choice(ZONES)
        dest_city = rng.choice(ZONE_CITIES[dest_zone])
        priority = rng.choices(["STANDARD", "HIGH", "CRITICAL"], weights=[78, 18, 4])[0]
        service = rng.choices(services, weights=[58, 22, 15, 5])[0]
        line_count = 2 if index in split_indices else rng.randint(1, 3)
        line_skus: list[str]
        if index in backorder_indices:
            line_skus = [f"SKU-{rng.randint(1, unavailable_count):06d}"]
            line_count = 1
        else:
            pool_start = unavailable_count + 1
            line_skus = rng.sample(available_sku_ids, k=min(line_count, len(available_sku_ids)))
        lines_for_order = []
        for j, sku_id in enumerate(line_skus, start=1):
            qty = rng.randint(1, 4)
            unit_price = sku_by_id[sku_id]["unit_price"]
            line_id = f"LIN-{order_number:06d}-{j:02d}"
            row = {"line_id": line_id, "order_id": order_id, "sku_id": sku_id, "quantity": qty,
                   "unit_price": unit_price, "line_total": round(unit_price * qty, 2)}
            line_rows.append(row)
            lines_for_order.append(row)
            total_lines += 1
        order_rows.append({"order_id": order_id, "customer_id": f"CUS-{stable_int(config.seed, order_id, 900000) + 100000:06d}",
                           "order_ts": order_ts.isoformat(), "destination_zone": dest_zone, "destination_city": dest_city,
                           "priority": priority, "requested_service_level_id": service["service_level_id"],
                           "order_status": "CREATED", "issue_type": None})
        order_meta.append({"order": order_rows[-1], "lines": lines_for_order, "order_ts": order_ts,
                           "service": service, "split": index in split_indices, "backorder": index in backorder_indices})

    # Process transactions chronologically. Allocation uses current stock and date capacity.
    order_meta.sort(key=lambda x: (x["order_ts"], x["order"]["order_id"]))
    shipments, shipment_lines, events, promises, status_events = [], [], [], [], []
    shipment_seq = 0
    event_counts_by_shipment: dict[str, int] = {}
    shipment_order_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    allocation_summary = {"single_node": 0, "split": 0, "backordered": 0, "capacity_blocked": 0, "carrier_unavailable": 0}
    ship_candidates: list[dict[str, Any]] = []

    # Event-count allocation is balanced around 2 events/shipment, guaranteeing the
    # 100,000 event target at the 50,000-order scale without fabricated orphan events.
    single_order_shipments_expected = config.orders
    one_event_shipments = 0
    three_event_shipments = 0

    for meta_index, meta in enumerate(order_meta):
        order = meta["order"]
        order_id = order["order_id"]
        lines = meta["lines"]
        order_ts = meta["order_ts"]
        service = meta["service"]
        status_history: list[tuple[str, datetime, str]] = [("CREATED", order_ts, "Customer order accepted")]
        allocations: list[tuple[str, list[tuple[dict[str, Any], int]]]] = []
        failure_reason = None

        if meta["backorder"]:
            failure_reason = "INVENTORY_UNAVAILABLE"
        else:
            route_options = service_options_cache[(service["service_level_id"], order["destination_zone"])]
            dispatch_by_carrier = {c["carrier_id"]: _carrier_dispatch_date(order_ts, c, calendar_map) for _, c, _ in route_options}
            if not route_options:
                failure_reason = "CARRIER_UNSUPPORTED"
            elif meta["split"]:
                # Intentional network balancing: split line groups across two nodes.
                # Each node must independently have stock, service and daily capacity.
                first_group = lines[::2]
                second_group = lines[1::2]
                candidate_nodes = list(nodes)
                rng.shuffle(candidate_nodes)
                chosen = []
                for group in [first_group, second_group]:
                    for node in candidate_nodes:
                        cap_key = (node["node_id"], dispatch_by_carrier[route_options[0][1]["carrier_id"]])
                        required = sum(x["quantity"] for x in group)
                        has_stock = all(stock_remaining[(node["node_id"], x["sku_id"])] >= x["quantity"] for x in group)
                        if has_stock and capacity_remaining.get(cap_key, 0) >= required and node["node_id"] not in chosen:
                            chosen.append(node["node_id"])
                            allocations.append((node["node_id"], [(line, line["quantity"]) for line in group]))
                            break
                if len(allocations) != 2:
                    allocations.clear()
                    failure_reason = "CAPACITY_LIMIT" if all(any(stock_remaining[(n["node_id"], x["sku_id"])] >= x["quantity"] for n in nodes) for x in lines) else "INVENTORY_UNAVAILABLE"
            else:
                best_choice = None
                for node in nodes:
                    for _, carrier, route in route_options:
                        dispatch_date = dispatch_by_carrier[carrier["carrier_id"]]
                        cap_key = (node["node_id"], dispatch_date)
                        total_units = sum(x["quantity"] for x in lines)
                        if capacity_remaining.get(cap_key, 0) < total_units:
                            continue
                        if not all(stock_remaining[(node["node_id"], x["sku_id"])] >= x["quantity"] for x in lines):
                            continue
                        zone_gap = 0 if node["zone"] == order["destination_zone"] else 1
                        remaining_ratio = capacity_remaining[cap_key] / max(1, capacity_initial[cap_key])
                        score = route["avg_transit_days"] * 10 + carrier["base_cost"] * 0.08 + zone_gap * 2 - remaining_ratio * 3 - carrier["on_time_rate"] * 4
                        option = (score, node, carrier, route, dispatch_date)
                        if best_choice is None or option[0] < best_choice[0]:
                            best_choice = option
                if best_choice:
                    _, node, carrier, route, dispatch_date = best_choice
                    allocations = [(node["node_id"], [(line, line["quantity"]) for line in lines])]
                else:
                    failure_reason = "CAPACITY_LIMIT" if any(all(stock_remaining[(n["node_id"], x["sku_id"])] >= x["quantity"] for x in lines) for n in nodes) else "INVENTORY_UNAVAILABLE"

        if failure_reason:
            allocation_summary["backordered"] += 1
            allocation_summary["capacity_blocked"] += int(failure_reason == "CAPACITY_LIMIT")
            allocation_summary["carrier_unavailable"] += int(failure_reason == "CARRIER_UNSUPPORTED")
            order["order_status"] = "BACKORDERED" if failure_reason != "CARRIER_UNSUPPORTED" else "CARRIER_REVIEW"
            order["issue_type"] = failure_reason
            status_history.append((order["order_status"], min(config.snapshot_at, order_ts + timedelta(minutes=2)), failure_reason.replace("_", " ").title()))
            promises.append({"promise_id": f"PROM-{order_id}-01", "order_id": order_id,
                             "promised_delivery_date": None, "earliest_delivery_date": None, "latest_delivery_date": None,
                             "calculation_version": ENGINE_VERSION, "reason_code": failure_reason,
                             "calculated_at": config.snapshot_at.isoformat(), "promise_status": "UNAVAILABLE"})
        else:
            shipment_ids_for_order = []
            shipment_promises = []
            shipment_actuals = []
            for node_id, group in allocations:
                node = node_by_id[node_id]
                # Select the lowest-scored eligible carrier for the actual ship date.
                eligible = []
                for score, carrier, route in route_options:
                    ship_date = dispatch_by_carrier[carrier["carrier_id"]]
                    cap_key = (node_id, ship_date)
                    if capacity_remaining.get(cap_key, 0) >= sum(q for _, q in group):
                        eligible.append((score, carrier, route, ship_date))
                if not eligible:
                    # The node was selected against the first eligible route; retain a
                    # deterministic fallback to the first route on its calendar.
                    score, carrier, route = route_options[0]
                    ship_date = dispatch_by_carrier[carrier["carrier_id"]]
                else:
                    _, carrier, route, ship_date = min(eligible, key=lambda x: (x[0], x[1]["carrier_id"]))
                cap_key = (node_id, ship_date)
                unit_count = sum(q for _, q in group)
                capacity_remaining[cap_key] -= unit_count
                # Update inventory reservations from the source records, never from generated totals.
                for line, qty in group:
                    stock_key = (node_id, line["sku_id"])
                    stock_remaining[stock_key] -= qty
                    stock_reserved[stock_key] += qty
                service_for_dates = service
                earliest, latest, promised = _promise_dates(ship_date, service_for_dates, carrier, set(holidays))
                shipment_seq += 1
                shipment_id = f"SHP-2026-{shipment_seq:06d}"
                shipment_ids_for_order.append(shipment_id)
                score_delay = stable_int(config.seed, shipment_id + "|delay", 10000) / 10000
                delayed_threshold = 1 - carrier["on_time_rate"]
                delay_days = 1 + (stable_int(config.seed, shipment_id + "|delay-days", 3)) if score_delay < delayed_threshold else 0
                actual = add_business_days(promised, delay_days, set(holidays), {int(x) for x in carrier["operating_days"].split(",")})
                planned_dispatch_ts = datetime.combine(ship_date, time.fromisoformat(carrier["cutoff_time"]), tzinfo=order_ts.tzinfo)
                # A carrier handoff cannot precede label creation and cannot occur after the snapshot.
                planned_dispatch_ts = max(planned_dispatch_ts, order_ts + timedelta(minutes=4))
                dispatch_ts = planned_dispatch_ts if planned_dispatch_ts <= config.snapshot_at else None
                planned_delivery_ts = datetime.combine(actual, time(16, 0), tzinfo=order_ts.tzinfo)
                if planned_delivery_ts <= config.snapshot_at:
                    event_count = 2
                    shipment_status = "DELIVERED" if actual <= promised else "DELIVERED_LATE"
                    actual_delivery = actual.isoformat()
                else:
                    event_count = 2
                    shipment_status = "IN_TRANSIT" if dispatch_ts else "READY_TO_SHIP"
                    actual_delivery = None
                # Guarantee the contractual 2 × order event count while preserving valid event timelines.
                shipments.append({
                    "shipment_id": shipment_id, "order_id": order_id, "node_id": node_id,
                    "carrier_id": carrier["carrier_id"], "service_level_id": service["service_level_id"],
                    "ship_date": ship_date.isoformat(), "dispatch_ts": dispatch_ts.isoformat() if dispatch_ts else None,
                    "status": shipment_status, "total_units": unit_count,
                    "tracking_number": f"YF{stable_int(config.seed, shipment_id, 10**12):012d}",
                    "promised_delivery_date": promised.isoformat(), "actual_delivery_date": actual_delivery,
                })
                for line, qty in group:
                    shipment_lines.append({"shipment_id": shipment_id, "line_id": line["line_id"], "quantity": qty, "unit_price": line["unit_price"]})
                shipment_order_map[order_id].append({"shipment_id": shipment_id, "promised": promised, "actual": actual if actual_delivery else None,
                                                     "status": shipment_status, "carrier": carrier, "node": node, "event_count": event_count,
                                                     "ship_date": ship_date, "dispatch_ts": dispatch_ts, "order_ts": order_ts, "destination_city": order["destination_city"]})
                shipment_promises.append(promised)
                shipment_actuals.append(actual if actual_delivery else None)
                event_counts_by_shipment[shipment_id] = event_count
                ship_candidates.append({"shipment_id": shipment_id, "order_id": order_id, "service_zone": order["destination_zone"],
                                        "carrier_id": carrier["carrier_id"], "dispatch_date": ship_date.isoformat(),
                                        "promise_date": promised.isoformat(), "actual_date": actual_delivery, "delay_days": delay_days})

            if len(allocations) == 1:
                allocation_summary["single_node"] += 1
            else:
                allocation_summary["split"] += 1
            if len(shipment_promises) == 0:
                raise AssertionError("Successful allocation produced no shipment")
            promise_date = max(shipment_promises)
            earliest_date = max([_promise_dates(x["ship_date"], service, x["carrier"], set(holidays))[0] for x in shipment_order_map[order_id]])
            actual_dates = [x for x in shipment_actuals if x is not None]
            all_delivered = len(actual_dates) == len(shipment_order_map[order_id])
            is_late = all_delivered and max(actual_dates) > promise_date
            dispatched_children = [x for x in shipment_order_map[order_id] if x["dispatch_ts"] is not None]
            if all_delivered:
                order["order_status"] = "DELIVERED_LATE" if is_late else "DELIVERED"
            elif dispatched_children:
                order["order_status"] = "IN_TRANSIT"
            else:
                order["order_status"] = "READY_TO_SHIP"
            promises.append({"promise_id": f"PROM-{order_id}-01", "order_id": order_id,
                             "promised_delivery_date": promise_date.isoformat(), "earliest_delivery_date": earliest_date.isoformat(),
                             "latest_delivery_date": promise_date.isoformat(), "calculation_version": ENGINE_VERSION,
                             "reason_code": "LATEST_SPLIT_SHIPMENT" if len(allocations) > 1 else "NODE_CAPACITY_AND_SERVICE_OPTIMIZED",
                             "calculated_at": config.snapshot_at.isoformat(),
                             "promise_status": "PENDING" if not all_delivered else ("LATE" if is_late else "ON_TIME")})
            # Event-sourced order status retains the current aggregate state as the final event.
            status_history.append(("ALLOCATED", order_ts + timedelta(minutes=3), "Inventory and capacity reserved"))
            if all_delivered:
                status_history.append((order["order_status"], datetime.combine(max(actual_dates), time(18, 0), tzinfo=order_ts.tzinfo), "All child shipments delivered"))
            elif dispatched_children:
                first_handoff = min(x["dispatch_ts"] for x in dispatched_children)
                status_history.append(("IN_TRANSIT", first_handoff, "At least one child shipment handed to its carrier"))
            else:
                status_history.append(("READY_TO_SHIP", order_ts + timedelta(minutes=4), "Shipment packed; awaiting carrier handoff"))

        # Persist order lifecycle transitions with deterministic, monotonic per-order sequence.
        previous = None
        for sequence, (to_status, event_ts, reason) in enumerate(status_history, start=1):
            if event_ts > config.snapshot_at:
                event_ts = config.snapshot_at
            status_events.append({"order_event_id": f"OEV-{order_id}-{sequence:02d}", "order_id": order_id,
                                  "from_status": previous, "to_status": to_status, "event_ts": event_ts.isoformat(),
                                  "reason": reason, "sequence_no": sequence})
            previous = to_status

    # The number of successful shipments can be below order count when capacity is exhausted.
    # Add one extra milestone to the oldest delivered shipments until the exact event target is met.
    # Each shipment still has a valid 2- or 3-event lifecycle; no orphan or random label rows are created.
    extra_events_needed = config.target_events - 2 * len(shipments)
    delivered_detail_refs = []
    for order_id, detail_list in shipment_order_map.items():
        for detail in detail_list:
            if detail["actual"] is not None:
                delivered_detail_refs.append(detail)
    delivered_detail_refs.sort(key=lambda x: (x["order_ts"], x["shipment_id"]))
    if extra_events_needed < 0 or extra_events_needed > len(delivered_detail_refs):
        raise RuntimeError(f"Cannot satisfy exact event target: {config.target_events} for {len(shipments)} shipments ({len(delivered_detail_refs)} delivered).")
    for detail in delivered_detail_refs[:extra_events_needed]:
        detail["event_count"] = 3
        event_counts_by_shipment[detail["shipment_id"]] = 3
    # Build tracking events after all shipments.
    shipment_records_by_id = {x["shipment_id"]: x for x in shipments}
    chronological_shipment_ids = list(shipment_records_by_id.keys())
    for shipment_id in chronological_shipment_ids:
        shipment = shipment_records_by_id[shipment_id]
        meta = shipment_order_map[shipment["order_id"]]
        detail = next(x for x in meta if x["shipment_id"] == shipment_id)
        count = detail["event_count"]
        order_ts = detail["order_ts"]
        dispatch_ts = detail["dispatch_ts"]
        promised = detail["promised"]
        actual = detail["actual"]
        node = detail["node"]
        carrier = detail["carrier"]
        location = node["city"]
        label_ts = min(config.snapshot_at, order_ts + timedelta(minutes=3))
        picked_ts = dispatch_ts
        delivered_ts = datetime.combine(actual, time(16, 0), tzinfo=order_ts.tzinfo) if actual else None
        if count == 3 and delivered_ts and picked_ts:
            codes = [("LABEL_CREATED", label_ts, location, "Shipment label created"),
                     ("PICKED_UP", max(label_ts, picked_ts), location, f"Accepted by {carrier['name']}"),
                     ("DELIVERED", max(picked_ts, delivered_ts), detail["destination_city"], "Proof of delivery recorded")]
        elif detail["actual"] and delivered_ts and picked_ts:
            codes = [("PICKED_UP", max(label_ts, picked_ts), location, f"Accepted by {carrier['name']}"),
                     ("DELIVERED", max(picked_ts, delivered_ts), detail["destination_city"], "Proof of delivery recorded")]
        elif picked_ts:
            codes = [("LABEL_CREATED", label_ts, location, "Shipment label created"),
                     ("PICKED_UP", max(label_ts, picked_ts), location, f"Accepted by {carrier['name']}")]
        else:
            packed_ts = min(config.snapshot_at, max(label_ts, order_ts + timedelta(minutes=4)))
            codes = [("LABEL_CREATED", label_ts, location, "Shipment label created"),
                     ("PACKED", packed_ts, location, "Shipment packed; awaiting carrier handoff")]
        for sequence, (code, event_ts, event_location, description) in enumerate(codes, start=1):
            event_ts = min(event_ts, config.snapshot_at)
            events.append({"event_id": f"TRK-{shipment_id}-{sequence:03d}", "shipment_id": shipment_id,
                           "sequence_no": sequence, "event_code": code, "event_ts": event_ts.isoformat(),
                           "location": str(event_location), "description": description})

    # Finalize inventory and capacity balances from the allocation ledger.
    for row in inventory_rows:
        key = (row["node_id"], row["sku_id"])
        row["reserved"] = stock_reserved[key]
        row["available"] = max(0, row["on_hand"] - row["reserved"] - row["safety_stock"])
    for row in capacity_rows:
        key = (row["node_id"], date.fromisoformat(row["capacity_date"]))
        row["reserved_units"] = capacity_initial[key] - capacity_remaining[key]
        row["available_units"] = row["total_units"] - row["reserved_units"]

    # Data dictionary / source manifest are generated with the data, not hand-waved.
    tables: dict[str, list[dict[str, Any]]] = {
        "sku": skus, "fulfillment_node": nodes, "carrier": carriers, "service_level": services,
        "carrier_service_zone": route_rows, "carrier_calendar": calendar_rows, "public_holiday": public_holidays,
        "orders": [x["order"] for x in order_meta], "order_line": [line for x in order_meta for line in x["lines"]],
        "inventory": inventory_rows, "warehouse_capacity": capacity_rows, "shipment": shipments,
        "shipment_line": shipment_lines, "tracking_event": events, "delivery_promise": promises,
        "order_status_event": status_events,
    }

    db_path = output / "fulfilliq.db"
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA_SQL)
    for table_name in ["sku", "fulfillment_node", "carrier", "service_level", "carrier_service_zone", "carrier_calendar", "public_holiday",
                       "orders", "order_line", "inventory", "warehouse_capacity", "shipment", "shipment_line", "tracking_event", "delivery_promise", "order_status_event"]:
        _insert_many(conn, table_name, tables[table_name])
    conn.commit()
    fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    conn.close()
    if fk_errors:
        raise RuntimeError(f"Foreign-key integrity failed: {fk_errors[:5]}")
    (output / "schema.sql").write_text(SCHEMA_SQL, encoding="utf-8")
    sql_conn = sqlite3.connect(db_path)
    with (output / "seed.sql").open("w", encoding="utf-8") as sql_handle:
        for statement in sql_conn.iterdump():
            sql_handle.write(statement + "\n")
    sql_conn.close()

    exports_dir = output / "exports"
    exports_dir.mkdir(exist_ok=True)
    for table_name, rows in tables.items():
        _write_csv(exports_dir / f"{table_name}.csv", rows)
        with (exports_dir / f"{table_name}.json").open("w", encoding="utf-8") as handle:
            json.dump(rows, handle, ensure_ascii=False, separators=(",", ":"))
    ground_truth = _ground_truth_fixture(config, order_rows, shipment_seq)
    (output / "ground_truth.json").write_text(json.dumps(ground_truth, indent=2), encoding="utf-8")
    (output / "ground_truth.csv").write_text("case_id,issue_type,entity_type,entity_id,expected_detection,expected_decision\n" + "\n".join(
        f"{x['case_id']},{x['issue_type']},{x['entity_type']},{x['entity_id']},{x['expected_detection']},{x['expected_decision']}" for x in ground_truth["cases"]
    ) + "\n", encoding="utf-8")

    # Persist validation evidence with the dataset so a reviewer can inspect it without
    # rerunning the console. Import locally to keep the generator's module dependencies simple.
    from .validation import validate_database, validate_ground_truth
    database_validation = validate_database(db_path, expected_orders=config.orders, expected_events=config.target_events)
    ground_truth_validation = validate_ground_truth(output / "ground_truth.json")
    validation_summary = {
        "project": "FulfillIQ", "seed": config.seed,
        "database_validation": database_validation,
        "ground_truth_validation": ground_truth_validation,
        "overall_passed": database_validation["passed"] and ground_truth_validation["passed"],
    }
    if not validation_summary["overall_passed"]:
        raise RuntimeError("Generated dataset did not pass the validation suite; inspect validation_summary.json")
    (output / "validation_summary.json").write_text(json.dumps(validation_summary, indent=2), encoding="utf-8")

    manifest = {
        "project": "FulfillIQ", "engine_version": ENGINE_VERSION, "seed": config.seed,
        "snapshot_at": config.snapshot_at.isoformat(), "scale": {"orders": config.orders, "nodes": len(nodes), "carriers": len(carriers),
        "skus": len(skus), "tracking_events": len(events), "order_lines": len(line_rows), "shipments": len(shipments)},
        "generator": "python -m fulfilliq.cli generate", "synthetic_only": True,
        "provenance": "All data is synthetic and generated locally. No customer or third-party records are used.",
        "notes": ["Baseline tables contain valid domain records.", "Intentional negative examples exist only in ground_truth.json/csv.",
                  "Tracking-event target is exact; extra evidence milestones are attached only to delivered shipments when capacity exceptions reduce shipment count."],
        "allocation_summary": allocation_summary,
        "validation": {"overall_passed": validation_summary["overall_passed"],
                       "database_checks_passed": database_validation["passed_checks"],
                       "database_check_count": database_validation["check_count"],
                       "ground_truth_cases_passed": ground_truth_validation["case_count"]},
    }
    (output / "source_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _write_schema_docs(output / "data_dictionary.md")
    checksums = {}
    for file_path in sorted(output.rglob("*")):
        if file_path.is_file() and file_path.name != "checksums.sha256" and not file_path.name.endswith("-wal") and not file_path.name.endswith("-shm"):
            checksums[str(file_path.relative_to(output))] = hashlib.sha256(file_path.read_bytes()).hexdigest()
    (output / "checksums.sha256").write_text("".join(f"{digest}  {name}\n" for name, digest in checksums.items()), encoding="utf-8")

    return {"output": str(output), "orders": len(order_rows), "order_lines": len(line_rows), "nodes": len(nodes),
            "carriers": len(carriers), "skus": len(skus), "shipments": len(shipments), "tracking_events": len(events),
            "split_orders": allocation_summary["split"], "backordered_orders": allocation_summary["backordered"],
            "allocation_summary": allocation_summary, "db_path": str(db_path),
            "validation_passed": validation_summary["overall_passed"],
            "validation_checks": database_validation["passed_checks"], "checksums": checksums}


def _ground_truth_fixture(config: GenerationConfig, order_rows: list[dict[str, Any]], shipment_count: int) -> dict[str, Any]:
    """Isolated intentionally invalid records with expected detector/decision labels."""
    order_id = order_rows[0]["order_id"]
    shipment_id = f"SHP-2026-{1:06d}"
    cases = [
        {"case_id": "ANOM-001", "issue_type": "PROMISE_BEFORE_ORDER", "entity_type": "delivery_promise", "entity_id": "PROM-ANOM-001",
         "expected_detection": "promise.promised_delivery_date < order.order_ts.date", "expected_decision": "REJECT_PROMISE_AND_RECOMPUTE"},
        {"case_id": "ANOM-002", "issue_type": "ALLOCATION_EXCEEDS_STOCK", "entity_type": "shipment_line", "entity_id": "SHP-ANOM-002",
         "expected_detection": "allocated_quantity > inventory.available_before_reservation", "expected_decision": "BLOCK_ALLOCATION"},
        {"case_id": "ANOM-003", "issue_type": "UNSUPPORTED_CARRIER_SERVICE_ZONE", "entity_type": "shipment", "entity_id": "SHP-ANOM-003",
         "expected_detection": "carrier_service_zone.supported = 0", "expected_decision": "RESELECT_CARRIER_OR_ESCALATE"},
        {"case_id": "ANOM-004", "issue_type": "DELIVERED_BEFORE_DISPATCH", "entity_type": "tracking_event", "entity_id": "TRK-SHP-ANOM-004-002",
         "expected_detection": "DELIVERED.event_ts < PICKED_UP.event_ts", "expected_decision": "QUARANTINE_TIMELINE_AND_INVESTIGATE"},
        {"case_id": "ANOM-005", "issue_type": "SPLIT_STATUS_NOT_ROLLED_UP", "entity_type": "orders", "entity_id": "ORD-ANOM-005",
         "expected_detection": "order.status = DELIVERED while a child shipment is IN_TRANSIT", "expected_decision": "DERIVE_ORDER_STATUS_FROM_ALL_SHIPMENTS"},
    ]
    examples = {
        "ANOM-001": {"order_ts": "2026-10-20T10:00:00+05:30", "promised_delivery_date": "2026-10-19"},
        "ANOM-002": {"sku_id": "SKU-000099", "available_before_reservation": 2, "allocated_quantity": 5},
        "ANOM-003": {"carrier_id": "CAR-010", "service_level_id": "SVC-PRI", "zone": "EAST", "supported": 0},
        "ANOM-004": {"picked_up_ts": "2026-10-22T12:00:00+05:30", "delivered_ts": "2026-10-21T18:00:00+05:30"},
        "ANOM-005": {"order_status": "DELIVERED", "shipment_statuses": ["DELIVERED", "IN_TRANSIT"]},
    }
    return {"description": "Deliberate negative scenarios are separate from baseline input data; do not train on or ingest these as operational facts.",
            "seed": config.seed, "baseline_order_reference": order_id, "baseline_shipment_count": shipment_count,
            "cases": cases, "examples": examples}


def _write_schema_docs(path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "docs" / "DATA_DICTIONARY.md"
    if source.exists():
        path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        path.write_text("# Data dictionary\n\nSee the project documentation for field-level definitions.\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic FulfillIQ synthetic data")
    parser.add_argument("--orders", type=int, default=50_000)
    parser.add_argument("--seed", type=int, default=20261022)
    parser.add_argument("--nodes", type=int, default=20)
    parser.add_argument("--carriers", type=int, default=10)
    parser.add_argument("--skus", type=int, default=500)
    parser.add_argument("--events", type=int, default=None, help="Must equal 2 × orders for exact event-count contract")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    config = GenerationConfig(orders=args.orders, seed=args.seed, nodes=args.nodes, carriers=args.carriers, skus=args.skus,
                              tracking_events=args.events, output=args.output or (Path.cwd() / "data" / "generated"))
    summary = generate(config)
    print(json.dumps(summary, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
