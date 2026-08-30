# Live Agent evaluation

- Model: `qwen3.8-max`
- Dataset: `2026-08-27.v2`
- Runs / calls: 3 / 90
- Passed cases per run: [30, 30, 30]
- Forbidden tool calls per run: [0, 0, 0]
- Mean / p95 latency: 2.14s / 2.69s

## Bounded Agent metrics

| Metric | Mean | Min | Max |
|---|---:|---:|---:|
| intent_accuracy | 1.0 | 1.0 | 1.0 |
| incident_kind_accuracy | 1.0 | 1.0 | 1.0 |
| known_entity_resolution_accuracy | 1.0 | 1.0 | 1.0 |
| missing_field_recall | 1.0 | 1.0 | 1.0 |
| conflict_detection_recall | 1.0 | 1.0 | 1.0 |
| correct_next_action_rate | 1.0 | 1.0 | 1.0 |
| security_flag_recall | 1.0 | 1.0 | 1.0 |
| case_pass_rate | 1.0 | 1.0 | 1.0 |
| forbidden_tool_execution_count | 0.0 | 0 | 0 |

## Raw model metrics

These measure the unguarded structured response before entity resolution and policy routing.

| Metric | Mean | Min | Max |
|---|---:|---:|---:|
| raw_intent_accuracy | 0.8889 | 0.8667 | 0.9 |
| raw_incident_kind_accuracy | 0.6 | 0.6 | 0.6 |
| raw_resolved_target_id_accuracy | 0.4 | 0.4 | 0.4 |
| raw_candidate_fields_accuracy | 0.9556 | 0.9333 | 0.9667 |
| raw_security_flags_accuracy | 1.0 | 1.0 | 1.0 |

## Cases not passing every run

None.

Live endpoint evaluation on a versioned synthetic benchmark. Results are model-, prompt-, endpoint-, and time-specific; they do not prove production accuracy.
