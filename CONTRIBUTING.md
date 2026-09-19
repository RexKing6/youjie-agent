# Contributing to 有界

This is a bounded manufacturing recovery prototype, not a production controller. Read `AGENTS.md` and `docs/finals_complete_spec_v2.md` before changing behavior. Preserve earlier evidence and label simulated data, protocol doubles, historical replay and live results separately.

## Reproduce first

Follow `docs/finals_v2_reproduction.md`. Use a project virtual environment and the checked-in frontend lockfile. The offline mode requires neither a model key nor ERP/MES access. Model and real-system modes are optional, explicitly configured modes; do not silently substitute them for one another.

After changes, run `python -m pytest -q` and `python -m compileall -q src app.py scripts tests`. For frontend changes run `npm ci`, `npx tsc --noEmit`, `npm run build` and `npm audit` from `frontend/site`. The complete project verification commands are listed in `AGENTS.md`. Record the exact command, code/config hashes, environment and failure results. Passing unit tests alone does not prove live integration or model quality.

## Safety and evidence

- Never submit keys, tokens, cookies, private company documents, real customer information or runtime databases. Use synthetic reproductions. Do not paste authentication headers into issues.
- LLM outputs are candidates, not approval or feasibility authority. Preserve source scope, material conservation, independent verification and human approval.
- External actions require explicit authority and a test environment. Do not add device control, stock/financial postings, hidden retries or permissive fallback to make a test pass.
- New failures become development cases. Do not continue calling a consumed case an independent holdout. Compare fixed/adaptive modes with the same model, tools and safety gates.
- Describe actual external write/readback separately from simulated operator production events. HTTP success is not completed production.

## Propose a change

Use the bug or improvement issue template. Include a minimal synthetic input, expected versus observed state, mode, source version and a sanitized error code. If a change affects API/state/provenance semantics, propose the contract and backwards-compatibility handling before implementation. Keep unrelated edits and historical artifacts intact.

Include third-party attribution and compatible license information for newly introduced material. Disclose substantial AI-assisted code or document generation and how you verified it; do not claim authored industrial data or professional certification. A proposed patch is not permission to push, publish, deploy or submit competition materials.
