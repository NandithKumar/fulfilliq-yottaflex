from __future__ import annotations

import tempfile
from pathlib import Path
import sqlite3

from fulfilliq import server as app_server
from fulfilliq.config import GenerationConfig
from fulfilliq.generator import generate
from fulfilliq.validation import validate_database, validate_ground_truth


def test_small_dataset_integrity_and_target_counts():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "data"
        result = generate(GenerationConfig(orders=120, seed=20261022, output=root))
        assert result["orders"] == 120
        assert result["shipments"] == 120
        assert result["tracking_events"] == 240
        validation = validate_database(root / "fulfilliq.db", expected_orders=120, expected_events=240)
        assert validation["passed"], validation["failed_checks"]
        assert validate_ground_truth(root / "ground_truth.json")["passed"]


def test_split_and_backorder_cohorts_are_labelled_and_balanced():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "data"
        result = generate(GenerationConfig(orders=200, seed=20261022, output=root))
        assert result["allocation_summary"]["split"] == result["allocation_summary"]["backordered"]
        assert result["shipments"] == result["orders"]
        assert result["tracking_events"] == 2 * result["orders"]


def test_fixed_seed_regenerates_same_csv_exports():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        a, b = root / "a", root / "b"
        generate(GenerationConfig(orders=80, seed=7, output=a))
        generate(GenerationConfig(orders=80, seed=7, output=b))
        for name in ["orders.csv", "shipment.csv", "tracking_event.csv", "inventory.csv"]:
            assert (a / "exports" / name).read_bytes() == (b / "exports" / name).read_bytes()


def test_different_seed_changes_generated_records():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        a, b = root / "a", root / "b"
        generate(GenerationConfig(orders=80, seed=7, output=a))
        generate(GenerationConfig(orders=80, seed=8, output=b))
        assert (a / "exports" / "orders.csv").read_bytes() != (b / "exports" / "orders.csv").read_bytes()


def test_allocation_preview_and_split_capacity_ledger():
    sample_db = Path(__file__).resolve().parents[1] / "data" / "sample" / "fulfilliq.db"
    previous_db = app_server.DB_PATH
    app_server.DB_PATH = sample_db
    try:
        with sqlite3.connect(sample_db) as conn:
            sku_ids = [row[0] for row in conn.execute(
                "SELECT sku_id FROM inventory GROUP BY sku_id HAVING MAX(available)>=90 ORDER BY SUM(available) DESC LIMIT 10"
            )]
        single = app_server.preview_decision({
            "zone": "SOUTH", "service_level": "STANDARD", "order_time": "2026-11-03T10:30:00+05:30",
            "lines": [{"sku_id": sku_ids[0], "quantity": 1}],
        })
        assert single["decision"] == "ALLOCATE_SINGLE_NODE"
        assert single["chosen"]["feasible"] is True

        split = app_server.preview_decision({
            "zone": "SOUTH", "service_level": "STANDARD", "order_time": "2026-11-03T10:30:00+05:30",
            "lines": [{"sku_id": sku_id, "quantity": 90} for sku_id in sku_ids],
        })
        assert split["decision"] == "ALLOCATE_SPLIT"
        assert len(split["split_plan"]) == len(sku_ids)
        assert len({item["node_id"] for item in split["split_plan"]}) > 1
        assert split["order_promise"] == max(item["latest_promise"] for item in split["split_plan"])

        capacity_usage = {}
        stock_usage = {}
        for item in split["split_plan"]:
            capacity_key = (item["node_id"], item["dispatch_date"])
            stock_key = (item["node_id"], item["sku_id"])
            capacity_usage[capacity_key] = capacity_usage.get(capacity_key, 0) + item["quantity"]
            stock_usage[stock_key] = stock_usage.get(stock_key, 0) + item["quantity"]
        with sqlite3.connect(sample_db) as conn:
            for (node_id, capacity_date), quantity in capacity_usage.items():
                available = conn.execute(
                    "SELECT available_units FROM warehouse_capacity WHERE node_id=? AND capacity_date=?",
                    (node_id, capacity_date),
                ).fetchone()[0]
                assert quantity <= available
            for (node_id, sku_id), quantity in stock_usage.items():
                available = conn.execute(
                    "SELECT available FROM inventory WHERE node_id=? AND sku_id=?", (node_id, sku_id)
                ).fetchone()[0]
                assert quantity <= available
    finally:
        app_server.DB_PATH = previous_db
