"""Command-line interface for generating, validating, serving and reproducing data."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from .config import ROOT, SAMPLE_DIR, GENERATED_DIR
from .generator import generate
from .config import GenerationConfig
from .server import main as serve
from .validation import validate_database, validate_ground_truth, render_summary


def _checksums(root: Path):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name not in {"checksums.sha256"} and not path.name.endswith(("-wal", "-shm")):
            result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(prog="fulfilliq", description="FulfillIQ network control tower")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="Generate deterministic CSV/JSON/SQLite data")
    gen.add_argument("--orders", type=int, default=50000)
    gen.add_argument("--seed", type=int, default=20261022)
    gen.add_argument("--nodes", type=int, default=20)
    gen.add_argument("--carriers", type=int, default=10)
    gen.add_argument("--skus", type=int, default=500)
    gen.add_argument("--events", type=int, default=None)
    gen.add_argument("--output", type=Path, default=GENERATED_DIR)
    val = sub.add_parser("validate", help="Run referential, business-rule and lifecycle checks")
    val.add_argument("--db", type=Path, default=None)
    val.add_argument("--orders", type=int, default=None)
    val.add_argument("--events", type=int, default=None)
    val.add_argument("--json", action="store_true")
    sub.add_parser("serve", help="Start the local operations dashboard")
    rep = sub.add_parser("reproduce", help="Generate twice and compare every output checksum")
    rep.add_argument("--orders", type=int, default=1000)
    rep.add_argument("--seed", type=int, default=20261022)
    rep.add_argument("--nodes", type=int, default=20)
    rep.add_argument("--carriers", type=int, default=10)
    rep.add_argument("--skus", type=int, default=500)
    args = parser.parse_args(argv)

    if args.command == "generate":
        config = GenerationConfig(orders=args.orders, seed=args.seed, nodes=args.nodes, carriers=args.carriers,
                                  skus=args.skus, tracking_events=args.events, output=args.output)
        result = generate(config)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "validate":
        db_path = args.db or (GENERATED_DIR / "fulfilliq.db" if (GENERATED_DIR / "fulfilliq.db").exists() else SAMPLE_DIR / "fulfilliq.db")
        result = validate_database(db_path, args.orders, args.events)
        gt_path = db_path.parent / "ground_truth.json"
        result["ground_truth"] = validate_ground_truth(gt_path) if gt_path.exists() else None
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(render_summary(result))
            if result["ground_truth"]:
                print(f"\nGROUND TRUTH FIXTURE: {'PASS' if result['ground_truth']['passed'] else 'FAIL'} ({result['ground_truth']['case_count']} cases)")
        return 0 if result["passed"] and (not result["ground_truth"] or result["ground_truth"]["passed"]) else 1
    if args.command == "serve":
        return serve()
    if args.command == "reproduce":
        with tempfile.TemporaryDirectory(prefix="fulfilliq-repro-") as tmp:
            root = Path(tmp)
            cfg = dict(orders=args.orders, seed=args.seed, nodes=args.nodes, carriers=args.carriers, skus=args.skus)
            a, b = root / "run_a", root / "run_b"
            generate(GenerationConfig(**cfg, output=a))
            generate(GenerationConfig(**cfg, output=b))
            ca, cb = _checksums(a), _checksums(b)
            differences = sorted(set(ca) | set(cb))
            differences = [name for name in differences if ca.get(name) != cb.get(name)]
            print(json.dumps({"passed": not differences, "seed": args.seed, "orders": args.orders,
                              "files_compared": len(ca), "mismatches": differences}, indent=2))
            return 0 if not differences else 1
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
