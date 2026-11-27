# Evidence: same input, with and without this Skill

These are **local practice runs**, not the official cases or scores. Each practice case was built from an open-access paper (CC BY) with a work order in the official format. Both conditions ran the same DeepSeek harness with the official budget (64 requests, 900 s, 16384 output tokens per response), the same input and the same tools. Effect scores come from one LLM judge (kimi-k3.1-pro) that rated the actual effect only (completion 15, correctness 15, completeness 5, verifiability 5 = 40) from the delivered files; repeated judging of one run varies by about +/-4. Run counts are small. Read this as a reproducible record, not as a benchmark claim.

### Practice case: nutrient-response models, presentation storyline

| condition | runs | runs with deliverables | local effect score /40, mean (range) | seconds, mean (range) | model requests, mean (range) |
|---|---|---|---|---|---|
| without Skill | 1 | 1 | 29 | 515 | 42 |
| with this Skill (v1.7-1.24) | 14 | 13 | 30.1 (27-33) | 663.2 (490-900) | 27.4 (15-44) |

## What the Skill adds that the agent did not do on its own

- Slides are written as a short spec; the engine builds the PPTX in the supplied template, renders the PDF, reads both back and writes the result record.
- Every number on a slide is searched in the passage or table it cites; carried-over text is matched to the original slide and, where possible, to a paper passage that contains all of its numbers.
- Template inheritance (masters, layouts, theme) and untouched slides are verified by canonical-XML and deep hashes; adaptation loss is audited element by element (text, tables, chart data, images, notes, hyperlinks, hidden slides).
- `python3 scripts/deckkit.py selftest` reproduces the checks on a synthetic example.

## Limits

The judge scores only the effect dimension; efficiency is shown by seconds and requests above. Where the agent without the Skill already produced a complete, well-sourced result, the Skill's gain is mainly in completion time, traceability and checked files rather than in the judged score; some practice runs with the Skill scored lower than the baseline run. The Skill does not decide scientific truth: it binds each drawn or written claim to the source and discloses what it could not verify.
