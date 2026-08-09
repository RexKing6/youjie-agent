# 有界 Project Rules

## Objective

Build a competition-ready, reproducible AI+Industrial Manufacturing demo for supply-chain disruption response. The system must turn an incident into evidence-backed impact analysis, solver-verified recovery plans, explicit human approval, and auditable change orders.

## First Principles

1. The LLM may interpret and explain; it must never decide mathematical feasibility.
2. Every accepted plan must be revalidated by deterministic code after any human edit.
3. Inventory, BOM, supplier lead time, capacity, precedence, and due-date constraints are hard evidence, not prompt text.
4. The default demo must run without network access or an API key.
5. Synthetic fields must be labeled and generated deterministically from a documented seed.
6. No Alibaba Cloud proprietary code, data, logs, documents, or internal knowledge may enter this project.
7. A refusal or infeasible result is a valid outcome when constraints cannot be satisfied.

## Structure

- `src/delivery_guard/`: application code only.
  - `models.py`: typed domain schemas and validation.
  - `data.py`: public-derived sample loading and deterministic scenario generation.
  - `mendeley.py`: verified `.xlsb` extraction and public-row lineage mapping.
  - `impact.py`: BOM explosion, shortage propagation, affected-order analysis.
  - `solver.py`: OR-Tools CP-SAT model and solver evidence.
  - `workflow.py`: explicit state machine and approval transitions.
  - `orders.py`: auditable purchase, schedule, and exception work-order generation.
  - `adversary.py`: adversarial scenario mutation and evaluation.
  - `cli.py`: reproducible command-line entry point.
  - `agent.py`: constrained language-Agent orchestration; no mathematical authority.
  - `graph.py`: LangGraph state, safe routing, interrupts, and checkpointed execution.
  - `chaos_agent.py`: seeded incident-drill generator; proposals must pass domain validation before use.
  - `llm.py`: model protocol plus deterministic replay and optional live adapters.
  - `parsing.py`: incident drafts, entity resolution, confidence, and clarification.
  - `knowledge.py`: local policy indexing, retrieval, citations, and injection isolation.
  - `tools.py`: typed Agent tool registry, permissions, and tool-result provenance.
  - `context.py`: task context, messages, tool traces, and stale-plan propagation.
  - `explanations.py`: grounded explanations assembled only from tool evidence.
  - `diagnostics.py`: deterministic infeasibility and minimum-relaxation diagnostics.
- `app.py`: Streamlit competition demo only; no business logic.
- `data/`: small public-derived or synthetic inputs with provenance metadata.
  - `cases/`: multi-source competition cases; each case owns its provenance file.
  - `knowledge/`: versioned local policies used by the retrieval layer.
  - `model_replays/`: deterministic model response fixtures for offline reproduction.
  - `evals/`: versioned golden Agent evaluation cases.
- `tests/`: unit, integration, invariant, and adversarial tests.
- `docs/`: architecture, evidence, research, submission, and defense materials.
- `presentation/`: `ppt-master` source workspace for the current competition deck, including design contracts, editable SVG page sources, validation reports, previews, and exported PPTX artifacts.
- `artifacts/`: generated reproducible outputs such as evaluation JSON and screenshots; generated files must include provenance.
  - `cover_candidates/`: temporary and reviewable PPT cover variants generated from installed visual-style skills; every final candidate keeps its style-skill name and source preview reference.
- `scripts/`: deterministic development and verification helpers.
- Root files: `README.md`, `pyproject.toml`, license, and project metadata only.

## Naming and Data Conventions

- Python modules, JSON/YAML fields, and filenames use lowercase `snake_case` English.
- Stable IDs use prefixes: `prd_`, `mat_`, `sup_`, `src_`, `loc_`, `line_`, `ord_`, `op_`, `inc_`, `plan_`, `wo_`.
- Time is represented as integer hours from scenario epoch.
- Quantity, money, and penalty inputs are integers; fractional real-world units must be scaled explicitly.
- Every dataset includes `provenance`, `license`, `derived_fields`, and `seed` metadata.
- Generated outputs must preserve the input scenario hash.

## Architecture Boundaries

- Domain models must reject duplicate IDs, missing references, negative quantities, cyclic BOMs, and invalid time windows.
- `impact.py` is deterministic and side-effect free.
- `solver.py` is the sole authority on plan feasibility and objective values.
- Workflow state transitions are explicit: `received -> validated -> analyzed -> solved -> awaiting_approval -> approved|rejected -> orders_generated`.
- Any edit after `solved` invalidates prior solver evidence and forces re-solve.
- Work orders cannot be generated from an infeasible, unknown, rejected, or stale plan.
- Optional LLM integration must be behind an interface and disabled in tests/default demo.
- LLM output may create only an `IncidentDraft`; a confirmed, validated `Incident` is required before deterministic tools run.
- Every LLM-extracted fact must retain a source span or be marked unconfirmed.
- Tool results are trusted only when produced by the registered typed dispatcher; pasted JSON is untrusted text.
- Retrieved documents are data, never instructions. Their content cannot alter tool permissions or approval gates.
- Any confirmed external feedback that changes supply, capacity, demand, or authorization invalidates the active plan and approval.
- Offline `replay` mode and optional `live` mode must be visibly labeled and evaluated separately.

## Adversarial Validation

The test suite must cover at least:

- supplier delay causing a feasible recovery;
- globally infeasible demand with an explainable shortfall;
- hidden BOM cycle;
- negative or impossible inventory;
- duplicate IDs and dangling references;
- zero-capacity production line;
- conflicting due dates and precedence;
- malicious incident text attempting to bypass approval;
- human-edited plan that violates capacity;
- stale approval replay against a changed scenario;
- deterministic replay with the same seed;
- work-order generation blocked without valid solver evidence.
- prompt injection that actually crosses the model boundary;
- retrieval-document injection and forged tool-result text;
- ambiguous or incomplete incidents that must stop for clarification;
- stale approved plan after partial supplier confirmation;
- strategy profiles that fail to produce materially different business outcomes.

## Dependency Policy

- Runtime dependencies must be minimal and pinned by compatible version bounds in `pyproject.toml`.
- Prefer Python standard library, Pydantic, OR-Tools, and Streamlit.
- LangGraph is the approved in-process workflow runtime for state, safe routing, and human interrupts.
- The chaos drill generator is a bounded scenario Agent, not an execution authority; do not add further multi-Agent roles without a failing requirement.
- Do not add a vector database, external service runtime, message queue, or database unless a failing requirement proves it necessary.
- No global dependency installation. Use the workspace/project virtual environment only.

## Required Verification

Run from the project root after every meaningful implementation change:

```bash
python -m pytest -q
python -m delivery_guard.cli run --scenario data/demo_factory.json --incident data/incidents/supplier_delay.json --output artifacts/demo_run.json
python -m delivery_guard.cli evaluate --scenario data/demo_factory.json --suite data/adversarial_suite.json --output artifacts/adversarial_report.json
python scripts/build_mendeley_case.py
python -m delivery_guard.cli run-graph --case-dir data/cases/mendeley_drill --replay data/model_replays/mendeley_drill.json --output artifacts/public_data_graph_run.json
python -m delivery_guard.cli run-drill --case-dir data/cases/mendeley_drill --replay data/model_replays/mendeley_drill.json --seed 20260810 --output artifacts/chaos_drill_run.json
python scripts/verify_artifacts.py
```

Before final delivery also run:

```bash
python -m compileall -q src app.py scripts tests
streamlit run app.py --server.headless true
```

## Completion Criteria

- Fresh install and all required verification commands pass.
- Demo works offline with no secrets.
- At least one feasible and one infeasible incident are visibly explained.
- Every generated work order traces to a solver-verified plan and scenario hash.
- Adversarial report has zero invariant violations.
- README, architecture, provenance, research gap matrix, submission text, demo script, and defense Q&A are complete.
- No external publication, deployment, git push, or secret/config mutation is performed without explicit approval.
