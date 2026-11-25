---
name: biological-pathway-diagram
description: Draw or edit biological mechanism and pathway diagrams (genes, proteins, complexes, compartments, activation, inhibition, modification, transport, feedback) from supplied primary sources, with evidence strength, editable SVG, PNG/PDF, entity and edge source map and result.json. Use for any pathway or mechanism figure task whose input is in /input with a figure-workorder.
---

# Biological mechanism and pathway diagram

Use for a biological mechanism or signalling/metabolic pathway figure; not for statistics, study design or prose. Each arrow is a claim: subject, action, object, place, evidence. Input: `/input` (case.json, task.md, materials, `artifacts/figure-workorder.json`). Output in `/app/output`: figure.svg/png/pdf, source map, edge table, edit record, result.json.

## Rules for this task

- No text panel and no items that repeat the legend, the footnotes or the caption: one diagram uses the whole page; at most 4 footnotes, each once. Grey edges carry their reference in the label ("ref 13"). Phospho-sites the paper names (also as antibody sites) go into the node note with that status.
- Must-show facts must be readable ON the figure (node note, edge label, text item or footnote), each with its comparator, unit and n; caption or result.json alone does not count. They stay visible in the edited version too. State factor levels and replicates in words ("control / treated, n = 3 per cell"), not as "2x3x3". A null result the order names (no interaction, n.s.) is written out.
- Do not shorten a chain: if the text says A inhibits B, which inhibits C, draw A, B and C (cited steps grey with the reference). A mechanism the authors only propose is still drawn, dotted, not dropped.
- An effect seen after a treatment starts at the treatment, not at its target. An inhibitor or knockdown result is an edge from that inhibitor/knockdown to what changed. A correlation or co-occurrence is `association`, never activation.
- A dependence shown for one ligand, substrate or cell line is not extended to its neighbours. Acute and prolonged effects are separate edges or labels with their times.
- Walk every feedback loop once, sign by sign: ligand -> receptor activation -> complex/dimer -> phosphorylation ... back to the start; a step drawn only as "binds" leaves the loop open.
- For each edge decide: subject (exact name and form), verb -> type (activates/induces `activation`; inhibits/represses/blocks `inhibition`; binds/recruits/forms complex `binding`; phosphorylates `phosphorylation`; ubiquitinates/acetylates/methylates... `modification` with the PTM name first in the label (the arrowhead then shows Ub, Ac, Me ...; otherwise M); cleaves/dephosphorylates `conversion` with the action as label in spec.json; enters/secreted/translocates `transport`; transcribes/translates `expression`; converts substrate `conversion`), object, condition/cell type/species, evidence (observed, knock-out, inhibitor, model, proposed), passage id.
- Direct versus indirect: if the source shows an effect without a direct interaction, keep the effect type and add the label "indirect". Knock-out of G lowers X: `activation` G -> X, "indirect". Drug lowers X: `inhibition` drug -> X, "indirect" unless X is its stated target. Direction missing in the source: `association` plus an `unresolved` entry. "No change / did not inhibit": no arrow; quote it as a text item.
- Names: genes italic `*Tp53*`, proteins upright, species prefix/case as printed; do not merge paralogues, subunits or isoforms, or rename to synonyms; complexes are one node of kind `complex` listing members in `note`. Gene or protein unclear, or one symbol for two things: keep the printed form, kind by what was assayed, and record the ambiguity in `unresolved`. A molecule shown in two compartments is two nodes joined by `transport`.
- Compartments are groups in the physical order outside -> membrane (`"kind":"membrane"`) -> cytoplasm -> organelle/nucleus, `"direction":"TB"`. Receptors/channels sit in the membrane group. Put a node in a compartment only when stated; otherwise leave it ungrouped and list it in `unresolved`.
- Feedback loops, crosstalk and branches must be explicit edges. Proposed or hypothetical ones get `"certainty":"proposed"`.
- Outcomes (kind `phenotype`) are the end of the chain, with the measured direction (increase/decrease) in the label. If data are supplied, add a chart panel rather than colouring nodes by eye.
- Do not add textbook steps that the supplied sources do not contain, even when they are true.

## How this works

You write small text files in `/app/work`. The bundled engine does everything mechanical: layout, orthogonal routing, vector drawing, SVG/PNG/PDF export, reading the delivered files back, resolving every citation, and writing a complete `/app/output/result.json`. Do not write your own drawing, export or JSON-assembly code, and during a run do not read the engine source, `examples/` or `guide.md`: everything needed is on this page (plus `charts.md` for a non-plain chart).

`S=/skills/weekly-skill/scripts` (use the directory this SKILL.md is in if it differs).

**Budget: 64 requests, 900 s; aim for about 20 calls. Hard limit: one response (thinking + text + tool call) over 16384 tokens aborts the whole run with nothing further saved.** This is the most common failure. Never think the whole figure through at once: decide at most 6 nodes or 6 relations per response, write them, go on.

| step | command | calls |
|---|---|---|
| 1 | `python3 $S/figkit.py start pathway` - **the first command, before opening any material file**: indexes the material, drafts `/app/work/spec.json` (canvas, panels, groups) from the work order and prints item 1 with its passages. You may `cat /input/task.md` and the work order; do not open the paper: each item brings its passages | 1 |
| 2 | per item: ONE command that appends this item's lines (at most 6 + 6) to `A.nodes`, `A.edges` in `/app/work`, then `python3 $S/figkit.py build && python3 $S/figkit.py next`. Repeat until ALL ITEMS VISITED. `find WORD` / `show P012-P014` / `table FILE` only for a named missing fact. | 6-9 |
| 3 | `python3 $S/figkit.py audit`; real conflicts and limits: `set unresolved "item \| conflict \| both values \| P008,P021"` and a line in `notes.items` (visible footnote) when a reader needs it; `set title "..."`, `set caption "..."`; `build` | 1-2 |
| + | **`python3 $S/figkit.py review`** after the content is complete - prints every claim next to the sentence it cites and the whole requirement list: correct wrong direction, sign, strength, condition, unit or citation; add every missing required item (use `show`/`table` to fetch it). It ends with POSSIBLY MISSING lines: close every real gap, rebuild, review again. Accuracy and completeness weigh far more than speed; watch the printed minutes: requested edit done by minute 8, verify by minute 10 (cut at 15; the model may be slow) | 1-3 |
| 4 | requested edit, once: change lines/spec, set edit_scope (Editing below), `python3 $S/figkit.py build --revise "what and why"`; supplied SVG: `svgtree` + `edit` | 1-3 |
| 5 | `read_image /app/output/figure.png` once; correct what a reader would misread | 1-2 |
| 6 | `python3 $S/figkit.py verify`, then stop. Be here by minute 10: the run is cut at minute 15 | 1 |

Line files (one item per line, fields separated by `|`, `-` for empty, no `|` inside a text; a later node/group line with the same id replaces the earlier one; `id | delete` removes a node, `from | to | type | delete` relations; to change a relation's type or label, delete it first, then append). Extra `key=value` fields (`rank=2`, `layer=perturbation_X`, `step=3`, `value=-0.41`, `dash=dotted`) count only AFTER all columns: edges 7, nodes 8, so fill skipped ones with `-`.

Text, timeline and footnote lines work the same way: `Q.items` / `C.items` (panel id): `value | text | src` (value `-` for a plain bullet); `notes.items` (footnotes): `- | text | src`; `T.items` (timeline panel T): `- | text | src | lane | start | end | at` (start and end for a period, or at = 1,3,7 for time points).

```
A.groups:  id | label | kind (membrane or -) | src
A.nodes:   id | label | kind | group | src | note | certainty | glyph
A.edges:   from | to | type | label | certainty | src | evidence (panel; cell line; perturbation; a few source words)
```

Format example (invented; never copy its content):

```
# A.groups
out | Extracellular | - | P004
mem | Plasma membrane | membrane | P004
cyt | Cytoplasm | - | P004
nuc | Nucleus | - | P007
# A.nodes
L | Ligand L | small_molecule | out | P004
RX | RX | receptor | mem | P004
ZK1 | ZK1 | enzyme | cyt | P004 | active form | stated
INH-7 | INH-7 | drug | cyt | P006
TF9 | TF9 | protein | cyt | P005
TF9n | TF9 (nuclear) | protein | nuc | P007
gla | *gla* | gene | nuc | P007 | - | stated | dna
# A.edges
L | RX | binding | - | stated | P004
RX | ZK1 | activation | indirect | stated | P004 | Fig 1B; HeLa; RX siRNA
INH-7 | ZK1 | inhibition | 1 uM, 1 h | stated | P006 | Fig 2A | layer=perturbation_INH7
ZK1 | TF9 | phosphorylation | pS12 | stated | P005,P008 | Fig 2C
TF9 | TF9n | transport | - | cited | P007
TF9n | gla | expression | induces | stated | P007
gla | RX | inhibition | feedback, untested | proposed | P009
```

Use the source's own name as node id (`INH-7`): it picks the sentence quoted as evidence. Follow the NEXT line each command prints. Have the first build before minute 4. After any build the deliverables are complete, so an interruption never leaves an empty output. Stop only after a review shows no real gap; do not polish appearance further and do not inspect files with your own scripts.

## Decide the science before drawing

1. Note from the work order: must-show items, forbidden claims, required sizes/formats, language, the edit request.
2. For each candidate arrow ask: does a passage state this relation, with this direction, under this condition? Stated or observed -> `"certainty":"stated"`. Proposed, hypothesised, "may", "suggests", model-only -> `"certainty":"proposed"` (drawn dashed, legend added automatically). Correlation -> type `association` (no arrowhead). Not supported -> leave it out and list it in `omitted` or `unresolved`.
3. Numbers: copy exactly as printed, with unit, n and meaning of the +/-. If text and table disagree, draw the table value and record both in `unresolved`.
4. Before finishing, go through the `audit` leads once: every real conflict or gap that touches the product (text vs table, n per analysis, dates, signs, units, interactions, corrections, missing design facts) becomes one `unresolved` entry with both values and passages. "Not significant" never becomes "no effect" or "equal". "Not reported" stays "not reported".
5. Every node, edge, chart and text item needs `src`: passage ids (`"P012"`, `["P012","P015"]`), a data file (`"file.csv"` or `"file.csv#3-9"`), or `"workorder"`. Cite the passage that states that exact fact. The engine searches every printed number in the cited source and reports those it cannot find.

## spec.json

Diagram content comes from the line files above. (A panel may instead hold `groups`/`nodes`/`edges` as JSON lists with the same column names as keys; an existing line file replaces that list.)

```json
{"title":"One-sentence claim the evidence supports","title_src":"P001",
 "canvas":{"width_mm":180,"font_pt":8,"dpi":300,"formats":[]},
 "layout":[["A"],["B","C"]],
 "panels":[
  {"id":"A","type":"diagram","title":"...","direction":"TB","src":"P003"},
  {"id":"B","type":"chart","chart":"bar","title":"...","data":"values.csv","x":"dose","y":"mean","group":"arm",
   "err":"sd","err_meaning":"SD, n = 5","xlabel":"Dose (mg)","ylabel":"Signal (a.u.)","where":{"day":["7"]},
   "src":["values.csv","P009"],"weight":1.4},
  {"id":"C","type":"text","title":"...","items":[{"value":"2.8 nm","text":"mean pore size","src":"P010"},{"text":"Not tested in vivo","src":"P014"}]}],
 "caption":"Self-contained caption: panels, abbreviations, n, error definition, what dashed means, not to scale.",
 "footnotes":[{"text":"Schematic, not to scale.","src":"workorder"}],
 "unresolved":[{"item":"...","state":"conflict|not reported|ambiguous","detail":"both values","src":["P008","P021"]}],
 "omitted":[{"item":"...","reason":"..."}],
 "decisions":["why this encoding/layout"]}
```

- `canvas`: exact page `"size_mm":[180,100]` (or `"size_px":[1600,1000]`) and smallest allowed text `"min_font_pt":7` when the work order gives them; extra export formats in `formats` (tiff, jpg, eps).
- node `kind`: protein receptor enzyme complex gene mrna small_molecule metabolite ion drug cell organism tissue phenotype process sample data result conclusion limitation concept
- edge `type`: activation inhibition binding dimerisation (double line) cleavage (dashed, scissors: shedding/proteolytic release) degradation phosphorylation modification transport expression conversion association causal path evidence contains flow signal comparison (add `"bidirectional":true` if stated)
- optional node keys: `note` (second, smaller line), `step` (number), `rank` (column/row index), `emphasis`, `certainty`, `glyph` (cell bacteria virus dna protein antibody mouse human brain heart lung plant leaf tube dish syringe pill microscope chart clock molecule droplet question)
- evidence status of nodes/edges, `certainty`: `stated`/`observed` (solid), `cited` (grey: from other literature), `proposed` (dashed). Extra per-edge record: `"evidence":{"panel":"Fig 3B","cell_line":"...","perturbation":"..."}` (goes to content_map and `edge_table.csv`). Only when the work order defines its own encoding: edge `width`, `dash` (solid dashed dotted), `color`, `double`; panel `"edge_width":{"field":"value","label":"|path coefficient|"}` maps each edge's `value` to line width and sign to colour with an automatic legend; spec `"legend_extra":[{"text":"p < 0.05","dash":"solid","width":3}]`, `"legend_labels":{"activation":"..."}`.
- `layer=perturbation_X` puts nodes/edges in their own SVG group `layer-perturbation_X`.
- charts: `"chart":"bar|stacked|line|scatter|dot|box|heatmap|forest"`, `where`, `group`, `err`/`lo`+`hi` with `err_meaning`, `stat`, `derive`, `reduce`, `overlays`; see `references/charts.md` before drawing anything beyond a plain chart.
- text markup everywhere: `*italic*`, `_{sub}`, `^{sup}`.
- Keep labels short (about 1-5 words); conditions go on the edge label or `note`; explanation goes to the caption. 6-18 nodes per diagram. `panels` in one row share width by `weight`; a nested list is a column, e.g. `[["A",["B","C"]]]` puts B above C to the right of A.

## Editing so that everything else is preserved

- Figure you built (always use this route for it, never `edit`): edit only the affected spec or line-file entries, add `"edit_scope":["id fragment", ...]` (element ids that may change, e.g. `"node-ZK1"`, `"layer-perturbation_X"`, `"A-edge-ZK1-"`) and/or `"edit_protect":["B-"]` (ids that must not change), then `build --revise "..."`. The first version is frozen as `figure_before_edit.*`; every later `--revise` is compared with it (a plain `build` starts a new v1). Removing an edge = append its `delete` line; adding text (an inset, a list, a note) = add a `text` panel at the end or a footnote, which is placed below so nothing above moves. Unaffected entities and connectors keep their geometry; before/after files, changed/added/removed ids, count of byte-identical elements and rollback are written to `edit_record.json`.
- SVG supplied by the case: `svgtree FILE.svg`, then `/app/work/ops.json` = `{"ops":[{"id":"label_3","op":"text","old":"5 mM","value":"5 uM","reason":"...","src":"P007"},{"id":"bar2","op":"attr","set":{"fill":"#0072B2"}},{"id":"grp","op":"remove|insert_after|insert_before|replace","svg":"<g .../>"}]}` and `python3 $S/figkit.py edit FILE.svg /app/work/ops.json --reason "..."`. Put extra `content_map`, `exceptions` or `allowed_ids` in `/app/work/edit_meta.json` before running. Elements outside the ops stay byte-identical.

## If something goes wrong

- `SPEC ERRORS` / `CANNOT DRAW`: nothing was overwritten; fix the named entry.
- `layout_collisions`: shorten labels, set `"direction":"LR"`, `"TB"` or `"WRAP"` (long numbered routes), move detail to `note`/caption, or split the panel.
- too tall: put panels side by side in `layout`, use LR, or cut nodes that no must-show item needs.
- `numbers_traceable`: cite the passage that has the number, or correct it; if it is computed, say so in the label and in `decisions` with the formula.
- too many relations to read: keep must-show ones, list the rest in `omitted`, or split into panels A and B (`B.nodes`, `B.edges`).
- human confirmation: you cannot give it; add to `decisions` "Not confirmed by a human; check first: ..." naming the 1-3 weakest relations.
- unreadable PDF/image or missing data: record it in `unresolved` with what you tried; never fill the gap from memory.
- No exporter or font: SVG and result.json stay valid; status becomes partial and says so. State separately what is missing, what cannot be judged and what failed to run.

`result.json` is written by the engine with the contract fields; do not rewrite it. If a case contract has extra root fields, add them with a few lines of Python that load, set and save the file after the last build.

For people, not needed in a run: `references/guide.md` (method, limits, maintenance) and `examples/synthetic` (complete sample input and spec; `python3 $S/figkit.py selftest`).
