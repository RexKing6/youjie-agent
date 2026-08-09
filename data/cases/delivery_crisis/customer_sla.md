---
document_id: policy_customer_sla_v1
version: 1
updated_at: 2026-08-09
license: Apache-2.0 synthetic fixture
---

# Customer delivery policy

## ColdChain A

Order A contains 40 Industrial Sensor Nodes and is due Friday at 20:00 in the scenario clock.
It is a critical order and must ship complete. Partial delivery requires a separate commercial approval
that is not granted in this scenario.

## Retail B

Order B contains 60 units and is due Friday at 20:00. Split delivery is allowed. The planner may
prioritize ColdChain A before Retail B when material or capacity is constrained.

## Channel C

Order C contains 40 units and is due the following Thursday. Split delivery is allowed.
