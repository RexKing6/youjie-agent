# Finals story alignment validation contract

Scope: approved PPT story implemented in the existing Demo, no new public deployment.

- Three real solver sources for qualified A1: emergency 8h / 8 CNY, regional transfer 24h / 3 CNY, original 8h + delay / 0 CNY. These are synthetic channel assumptions, not supplier quotes.
- Default: demand600, A1=200, approved A2=300, delay48h. Expected cost/completion/lateness: 800/12/0, 300/28/16, 0/60/48 under service/budget400/zero-cost policies.
- Never force three distinct answers for other inputs. Short delays, sufficient stock, and exhausted budget may legitimately converge.
- New typed local event: warehouse quarantines50 A1. Preserve approval history, invalidate current approval and drafts before re-solving. Gap100→150; emergency1200; regional requirement450 exceeds400 budget, so budget policy cannot silently spend450.
- This event changes only the synthetic scenario, not ERP stock. Block it after an external execution record exists, preserving existing authenticated MES reconciliation.
- Wiki updates show new registered source IDs and version change. Unverified prose grants no authority; do not claim global learned knowledge or model refresh when only compiled.
- Display orderX consistently in user-facing guidance; preserve scoped source identifiers and historical evidence internally.

Development checks: deterministic expected values, delays12/24/48/72, quantities400/600/650/1200, missing/forged evidence, stale/double event, restarted workflow, no automatic writes, strict event schema.
Independent online checks after freeze: default two replies, different order quantity/delay phrasing, irrelevant/profane/injection inputs, and simulated A1 quarantine. Same live model, no hidden retries/fallback. Failures preserved.
Integration: existing local ERPNext/OpenMES same-run write/readback/idempotency and production feedback validation remains mandatory; no native stock posting.
UI: TypeScript/lint and actual browser checks of comparisons, chart, event feedback and knowledge update. Full pytest and existing regression commands.
