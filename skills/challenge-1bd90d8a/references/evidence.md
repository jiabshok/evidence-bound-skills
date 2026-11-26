# Evidence: same input, with and without this Skill

These are **local practice runs**, not the official cases or scores. Each practice case was built from an open-access paper (CC BY) with a work order in the official format. Both conditions ran the same DeepSeek harness with the official budget (64 requests, 900 s, 16384 output tokens per response), the same input and the same tools. Effect scores come from one LLM judge (kimi-k3.1-pro) that rated the actual effect only (completion 15, correctness 15, completeness 5, verifiability 5 = 40) from the delivered files; repeated judging of one run varies by about +/-4. Run counts are small. Read this as a reproducible record, not as a benchmark claim.

### Practice case: culture time course, data chart + edit

| condition | runs | runs with deliverables | local effect score /40, mean (range) | seconds, mean (range) | model requests, mean (range) |
|---|---|---|---|---|---|
| without Skill | 1 | 1 | 34 | 570 | 29 |
| with this Skill (v1.7-1.10) | 3 | 3 | 34.0 (33-36) | 414.0 (179-586) | 25.3 (21-28) |

### Practice case: bee tongue length data, chart + edit

| condition | runs | runs with deliverables | local effect score /40, mean (range) | seconds, mean (range) | model requests, mean (range) |
|---|---|---|---|---|---|
| without Skill | 1 | 1 | 37 | 297 | 15 |
| with this Skill (v1.7-1.10) | 1 | 1 | 36 | 317 | 40 |

## What the Skill adds that the agent did not do on its own

- A figure is planned in small line files (at most 6 nodes or relations per response), so no single response has to hold the whole drawing; layout, routing, export and the result record are deterministic.
- Every drawn relation and number is traced to a passage or table row; a relation whose only cited sentence proposes it, correlates the two ends or reports earlier work is drawn dashed (proposed, or correlation with its sign kept) or grey (cited literature) and listed in `exceptions` (`EVIDENCE CLASS`).
- Delivered files are read back: entities and relations re-parsed from the SVG, chart geometry inverted through the axis calibration and compared with the table cells, type size measured at final physical size, the edit compared element by element with the frozen first version.
- `python3 scripts/figkit.py selftest` reproduces the checks on a synthetic example, including injected faults that must be caught (wrong chart value, dropped relation, edit outside its scope, missing export).

## Limits

The judge scores only the effect dimension; efficiency is shown by seconds and requests above. Where the agent without the Skill already produced a complete, well-sourced result, the Skill's gain is mainly in completion time, traceability and checked files rather than in the judged score; some practice runs with the Skill scored lower than the baseline run. The Skill does not decide scientific truth: it binds each drawn or written claim to the source and discloses what it could not verify.
