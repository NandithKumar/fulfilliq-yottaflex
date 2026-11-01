# FulfillIQ | Fulfillment Network Control Tower

**A deterministic, explainable fulfillment allocation and promise-date simulator.** Built for the YottaFlex AI Associate AI Forward Deployed Engineer 72-hour code challenge.

FulfillIQ turns a synthetic order stream into constrained fulfillment decisions, carrier-aware promises, shipment records, tracking timelines and auditable delivery outcomes. It includes a local operator dashboard, an allocation preview API, a relational SQLite store, CSV/JSON exports, five isolated negative scenarios and a database-backed validation suite.

> **Scope note:** This is a self-contained synthetic simulation, not a live integration with a retailer, warehouse or carrier. The system uses no external API keys, customer PII, proprietary source data or paid services. The core runtime is Python standard library only.

## Why this is more than a data generator

- **Constraint-aware allocation:** evaluates SKU availability, per-node/day warehouse capacity, carrier/service/zone support, operating calendars and local cutoffs.
- **Promise calculation:** calculates earliest/latest business-day windows and commits to the latest child-shipment promise for split orders.
- **Event traceability:** persists shipment tracking events and order state transitions as append-only records.
- **Derived outcomes:** carrier delay outcomes are calculated from documented reliability parameters and stable shipment-level hash signals, not assigned as free-floating labels.
- **Relational integrity:** SQLite primary keys, foreign keys, bridge tables, unique constraints, check constraints and indexes are used throughout.
- **Quality evidence:** validates 30 database, arithmetic, lifecycle and reconciliation conditions and keeps the five intentionally invalid challenge cases in a separate ground-truth fixture.
- **Reproducibility:** fixed seed, deterministic IDs, source manifest and SHA-256 checksums; a command regenerates the same build twice and compares outputs.
- **Operator console:** a polished local control tower includes KPIs, order flow, state distribution, node capacity, carrier reliability, exception watchlist, order drill-down, tracking timeline and a decision workbench.

## Quick start (Windows / macOS / Linux)

**Requirements:** Python 3.10 or later. No Node, Docker, cloud account, database server or API key is required.

### 1. Open the project folder

```bash
cd fulfilliq
```

### 2. (Optional) Create a virtual environment

Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

The dashboard and generator need no third-party Python package. Install `pytest` only if you want to run the optional pytest wrapper:

```bash
python -m pip install -r requirements.txt
```

### 3. Start the application

The repository includes a 250-order starter dataset, so the dashboard can open immediately:

```bash
python -m fulfilliq.cli serve
```

Open **http://127.0.0.1:8765** in your browser. Stop the server with `Ctrl+C`.

### 4. Validate the bundled starter dataset

```bash
python -m fulfilliq.cli validate --orders 250 --events 500
```

### 5. Generate the full assessment scale

```bash
python -m fulfilliq.cli generate --orders 50000 --nodes 20 --carriers 10 --skus 500 --events 100000 --seed 20261022 --output data/generated
```

Then run:

```bash
python -m fulfilliq.cli validate --db data/generated/fulfilliq.db --orders 50000 --events 100000
python -m fulfilliq.cli serve
```

The server automatically prefers `data/generated/fulfilliq.db` when it exists. To explicitly select another database:

Windows PowerShell:

```powershell
$env:FULFILLIQ_DB = "data/sample/fulfilliq.db"
python -m fulfilliq.cli serve
```

macOS / Linux:

```bash
FULFILLIQ_DB=data/sample/fulfilliq.db python -m fulfilliq.cli serve
```

## Application tour

| Workspace | What it demonstrates |
|---|---|
| **Control tower** | Order volume, on-time promise rate, unfulfilled rate, split-order share, state distribution, 45-day flow, node utilization, carrier reliability and exception watchlist. |
| **Order command** | Search and filter orders; open a full audit drawer showing source lines, shipment allocation, promise, carrier and tracking events. |
| **Allocation lab** | Submit a hypothetical order basket and inspect feasible node/carrier candidates, dispatch date, promise window, stock/capacity checks and an explainable decision. This endpoint is read-only. |
| **Network health** | Inspect all fulfillment nodes and the carrier scorecard. |
| **Data assurance** | Run SQL-backed validation checks and audit the five separate negative scenarios. |

## CLI reference

```text
python -m fulfilliq.cli generate [--orders N] [--seed N] [--nodes N] [--carriers N] [--skus N] [--events N] [--output PATH]
python -m fulfilliq.cli validate [--db PATH] [--orders N] [--events N] [--json]
python -m fulfilliq.cli reproduce [--orders N] [--seed N] [--nodes N] [--carriers N] [--skus N]
python -m fulfilliq.cli serve
```

`--events` is constrained to exactly `2 × orders` in order to demonstrate the challenge's 50,000-order / 100,000-event target. Starter and full data use the same generator and business rules.

## Repository layout

```text
fulfilliq/
├── fulfilliq/
│   ├── config.py             # seeds, snapshot and scale configuration
│   ├── schema.py             # canonical SQLite DDL and constraints
│   ├── generator.py          # master data, allocation, promise and event pipeline
│   ├── validation.py         # SQL-backed integrity and reconciliation suite
│   ├── server.py             # local HTTP API + static application host
│   ├── cli.py                # generate / validate / reproduce / serve
│   └── util.py               # deterministic IDs, hash signal and calendar helpers
├── web/
│   ├── index.html            # application shell
│   ├── styles.css            # responsive local UI
│   └── app.js                # dashboard, order explorer and allocation workbench
├── data/
│   └── sample/               # small executable starter database + CSV/JSON exports
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DECISION_POLICY.md
│   ├── VALIDATION.md
│   ├── CHALLENGE_MAPPING.md
│   └── DEMO_SCRIPT.md
├── tests/
├── PROMPT_HISTORY.md
├── requirements.txt
└── README.md
```

Full-scale generated output is written to `data/generated/` and is git-ignored so a large generated dataset does not overwhelm the public source repository. The smaller starter dataset is committed so reviewers can launch the dashboard without a long generation step.

## Data model

The relational model covers all entities requested in the challenge: `Order`, `OrderLine`, `SKU`, `FulfillmentNode`, `Inventory`, `WarehouseCapacity`, `Carrier`, `ServiceLevel`, `Shipment`, `TrackingEvent` and `DeliveryPromise`. It also includes `carrier_service_zone`, `carrier_calendar`, `public_holiday`, `shipment_line` and `order_status_event` to model many-to-many capabilities, calendars, shipment splits and append-only order state history.

The full field-level data dictionary, units, required/optional flags, allowed values, uniqueness rules, validation rules, lifecycle states and cardinalities are available in `docs/DATA_DICTIONARY.md` and copied into every generated data directory. Each generated dataset also includes a machine-readable `validation_summary.json` with the full check results and separate ground-truth audit.

## Key business rules

1. **Allocation feasibility:** node active + SKU availability + node/date capacity + supported carrier/service/zone + operational carrier date.
2. **Candidate score:** lower is better: `transit_days × 10 + carrier_base_cost × 0.08 + zone_gap × 2 − remaining_capacity_ratio × 3 − on_time_rate × 4`.
3. **Cutoff:** at/before local carrier cutoff may dispatch same day; after cutoff or on a closed day rolls to the next operational carrier date.
4. **Promise:** service-level min/max business days are added while skipping generated closure dates and non-operating weekdays. A split order's commitment is the latest child-shipment promise.
5. **Actual outcome:** a stable SHA-256 signal tied to seed and shipment ID is compared to `1 − carrier.on_time_rate`; qualifying shipments receive a deterministic 1–3 carrier-business-day delay.
6. **Order roll-up:** an order is delivered only after all child shipments are delivered.
7. **Anomalies:** the five requested negative cases are in `ground_truth.json/csv`, not baseline input data.

Read [Decision Policy](docs/DECISION_POLICY.md) for the assumptions and [Architecture](docs/ARCHITECTURE.md) for the system flow.

## Validation and reproducibility

The validator executes checks directly against the persisted SQLite database. It checks foreign keys, uniqueness, line arithmetic, inventory and capacity balances, shipment unit reconciliation, order/line consistency, allocation bounds, promise chronology and split roll-up, tracking chronology, carrier support, order promise coverage and exact event count.

Run a same-seed two-build comparison:

```bash
python -m fulfilliq.cli reproduce --orders 1000 --seed 20261022
```

The output directories include `source_manifest.json`, `validation_summary.json` and `checksums.sha256`. All generated values are synthetic. The manifest documents the seed, scale, snapshot, provenance and intentional anomaly separation. The completed full-scale verification produced 45,775 shipments, 1,378 split orders and 5,603 backordered/capacity-exception orders; all 30 database checks passed, all five anomaly classes were present, and an independent same-seed rebuild matched all 40 output files with zero checksum differences. See [Validation Evidence](docs/VALIDATION.md).

## Tests

```bash
python -m pytest -q
```

Tests use temporary directories and exercise dataset counts, integrity checks, split/backorder balance and deterministic seed behavior. The application itself does not need pytest to run.

## API surface

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Runtime/database health. |
| `GET` | `/api/summary` | Dashboard metrics, statuses, trend, nodes and exceptions. |
| `GET` | `/api/orders` | Search/filter/paginate order ledger. |
| `GET` | `/api/orders/{order_id}` | Full order, lines, shipments, events and allocation detail. |
| `GET` | `/api/skus` | SKU catalogue for decision preview. |
| `GET` | `/api/validation` | SQL-backed checks and ground-truth coverage. |
| `POST` | `/api/decision` | Read-only allocation recommendation preview. |

## Limitations and next steps

- Data is synthetic. The city/node map, carrier names, reliability rates and closure dates are simulation inputs, not current commercial facts.
- The current allocator is a deterministic heuristic, not a global mixed-integer optimizer. The score is intentionally visible and can be tuned.
- The preview endpoint is stateless and read-only. Production reservations need atomic inventory/capacity writes, concurrency control, idempotency and rollback.
- The HTTP server is intended for local assessment use. It has no authentication, TLS termination, role management or production deployment hardening.
- Carrier integrations, live WMS/OMS data, live holidays, geocoding, route distance APIs and customer notifications are out of scope.

## Submission handoff

See [`SUBMISSION_CHECKLIST.md`](SUBMISSION_CHECKLIST.md) for the public GitHub push steps, final portal checks and the explanation-round checklist. The full-scale generated data is reproducible locally and is intentionally excluded from Git.

## AI-use disclosure

AI assistance was used for implementation scaffolding, test design, documentation drafting and UI composition. The full user prompts and source inputs used in this ChatGPT work session are logged in [`PROMPT_HISTORY.md`](PROMPT_HISTORY.md). Reviewers should be told clearly which parts were AI-assisted. The candidate should personally run the commands, inspect the code, modify at least one design decision, and be able to explain the allocator, promise logic, event lifecycle, validation SQL and known limitations. No human co-author or external proprietary codebase was used in this workspace.

---

**Challenge target:** 50,000 orders · 20 fulfillment nodes · 10 carriers · 100,000 tracking events · seed `20261022`.
