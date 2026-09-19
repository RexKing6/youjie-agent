# Predeclared current guided-chain acceptance

Use the existing operator-authorized model and local ERPNext/OpenMES test instances only. Synthetic data, no production controls or stock posting. Do not reset credentials or databases; preserve prior runs.

- Guided input: A1 delay48h; first reply oral indication, second AP-PARTIAL + TECH-CURRENT approves300 A2.
- Assert order600, eligible A2=300, service-first incremental800, three verified plans. Archived MAIL-DELAY stays in global registry but not current evidence.
- Explicit test actor approves; create and read back dedicated test draft/record in both systems; repeated execution must return same ERP record.
- Operator simulates100 production in that exact OpenMES test record, polls it, confirms100 good/A1 consumed100 and elapsed2h. Remaining demand500, old approval invalid, awaiting new approval.
- After a new approval, automatic duplicate remaining work-order delivery must be rejected. Report unique record count.
- Execute existing `validate_finals_real_chain.py --guided-only` once; failure is retained and diagnosed, not rerun until green without disclosure.
- Run full pytest, frontend typecheck and actual UI inspection. No competition submission or publication.
