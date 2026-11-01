# YottaFlex submission checklist

## Before pushing

- [ ] Run `python -m pytest -q` and confirm all tests pass.
- [ ] Run `python -m fulfilliq.cli validate --orders 250 --events 500` and confirm 30/30 checks plus 5/5 ground-truth cases pass.
- [ ] Start the app with `python -m fulfilliq.cli serve` and open `http://127.0.0.1:8765`.
- [ ] In Allocation Lab, demonstrate a feasible single-node recommendation and a split or escalation case.
- [ ] Open an order trace and explain its lines, shipment allocations, promise and tracking events.
- [ ] Read `docs/DECISION_POLICY.md`, `docs/ARCHITECTURE.md` and `docs/DEMO_SCRIPT.md`.
- [ ] Review `PROMPT_HISTORY.md`; add every new prompt verbatim if another AI tool is used.
- [ ] Create a **public** empty GitHub repository. Do not add a README, licence or `.gitignore` on GitHub because these are already in this local repository.
- [ ] Push this repository and open the public URL in a private/incognito browser window to verify that it is visible without signing in.
- [ ] Paste the public repository URL into the YottaFlex portal and verify the URL before the one-time final submission.

## Push to your GitHub account

From this project directory, after creating an empty public repository named `fulfilliq-yottaflex`, replace `YOUR_GITHUB_USERNAME` below with your actual GitHub username:

```bash
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/fulfilliq-yottaflex.git
git branch -M main
git push -u origin main
```

If GitHub asks you to authenticate, complete its browser/device sign-in flow. Never put a password or personal access token into a source file or commit.

## Full-scale assessment dataset

The committed `data/sample/` database is deliberately small so the public repository remains easy to clone. Recreate the required 50,000-order / 100,000-event dataset locally with:

```bash
python -m fulfilliq.cli generate --orders 50000 --nodes 20 --carriers 10 --skus 500 --events 100000 --seed 20261022 --output data/generated
python -m fulfilliq.cli validate --db data/generated/fulfilliq.db --orders 50000 --events 100000
```

`data/generated/` is intentionally excluded from Git by `.gitignore`. The full-scale dataset is reproducible and includes the database, CSV/JSON exports, SQL seed, manifest, validation report, ground-truth fixtures and checksums.

## Be ready to explain

The candidate is responsible for the implementation, even where AI assistance was used. Be prepared to explain the allocation score and hard constraints, split-shipment inventory/capacity ledgers, carrier cutoffs and calendars, order promise roll-up, deterministic delivery-delay outcome, append-only event history, the five intentionally isolated anomalies, and the validation queries. The `PROMPT_HISTORY.md` file discloses AI assistance; do not claim unaided authorship.
