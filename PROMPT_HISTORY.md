# AI prompt history and usage disclosure

This file records the AI tool and the candidate prompts used for this project in the current work session. Update it if another AI tool is used after this file is created. The challenge requires prompts to be supplied; assistant responses are not required by the supplied FAQ. No hidden/system instructions are included.

## Tool inventory

| Tool | Use | Export limitation |
|---|---|---|
| ChatGPT (GPT-6) | Requirements interpretation, architecture planning, Python implementation scaffolding, validation design, dashboard composition and documentation drafting. | This conversation does not provide a one-click prompt export. The candidate request text and challenge source are recorded below. |
| Other external LLM/coding agents | None used by this implementation workflow. | Not applicable. |

## Prompt 001 · Initial build request

> so i think i upladed the required content u want so build a project like exactly they asked or even more impressive they can imagiine , i dont want the project lke a simple prototype and just naivce looking child makaable one and i want to impress them after this round theere wll a explanation round so i have to make it work n all costs and i wan tto impress theem as high as possible so make it with all ur might

**Attached source inputs:**

- `YottaFlex AI Candidate Project Submission Guidelines.pdf`
- `YottaFlex AI Candidate Project-FAQ.pdf`

## Prompt 002 · Full challenge supplied

> here u go i am saying agan i want the best u can make so use all the means and use al the ai tools websites and other weapons u have so make it the best

**Challenge source supplied in the same message:** the candidate portal problem statement for “72 Hours Code Challenge”, Associate AI Forward Deployed Engineers. It specifies fulfillment node and promise selection using inventory, warehouse capacity, carrier cutoffs and service levels; all 11 core entities; deterministic ID conventions; 50,000 orders, 20 nodes, 10 carriers and 100,000 events; five labelled anomaly scenarios; a fixed seed; validation; CSV/JSON/SQL seed data; README, schema/data dictionary, manifest and two-run reproducibility.

## How AI accelerated the work

- Drafted the package structure, SQLite schema, deterministic generator, CLI, local HTTP API, browser interface, tests and technical documentation.
- Suggested transparent, deterministic allocation and delivery-outcome rules rather than an opaque predictive model, because the challenge emphasizes explainability, domain constraints and ground-truth derivation.
- Helped structure SQL-backed validation and isolated negative fixtures.

## Candidate review and ownership checklist

Before submission, the candidate must personally:

1. Run the starter and full-scale generation/validation commands on their machine.
2. Open the local dashboard and exercise at least one single-node, one split or escalation scenario, and one order drill-down.
3. Read `docs/DECISION_POLICY.md`, `fulfilliq/generator.py`, `fulfilliq/validation.py` and `fulfilliq/server.py`; be able to explain each major rule and trade-off.
4. Inspect the generated files and verify that the manifest counts match the database.
5. Make and document any corrections or improvements they personally perform. Add additional prompt entries verbatim if they use ChatGPT, Gemini, Claude, Copilot or any other AI tool again.

**Important:** The code was AI-assisted. This disclosure does not claim that the candidate independently authored every line. The candidate remains responsible for reviewing, understanding, validating and being able to defend the submitted work, consistent with the candidate FAQ.
