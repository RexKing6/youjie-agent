# Plain-language entry validation

Scope: dropdown message presets plus editable text; no new business-parameter support.
Default `guided` fixture: A1=200, A2/B17 on_hand=400, hold=0; two human replies,
second example supplies AP-PARTIAL (300 units), leaving 100 units for recovery.
Preserve existing fixtures, evidence authority, approval gates and historical runs.

Acceptance: known 24/48/72-hour delays use exact values; unknown/ambiguous input
does not produce plans; oral permission cannot release material; scoped partial
approval yields verified cost/delay alternatives without external writes.
Build and typecheck frontend, run pytest and browser-check dropdown/custom editing.
Synthetic development regression only, not independent effectiveness evidence.
