---
name: scientific-schematic
description: Create or edit an editable relationship schematic (entities, hierarchy, parallel, sequence, causal or feedback relations) from supplied scientific material, with SVG source, PNG/PDF exports, entity and edge source map, edit record and result.json. Use for any schematic task whose input is in /input with a figure-workorder.
---

# Scientific schematic: create and edit from evidence

Use for a relationship schematic, conceptual framework or structure diagram, or an edit of one. Every containment, direction and relation type is a scientific statement.

**Do not read the paper up front** (no cat, grep or python on material.json, PDFs or text files). Runs that did used 6-12 of their 15 minutes before the first drawing and lost the edit. `start` and `next` select the passages for every requirement; open one more passage with `show` only when an item names a fact you cannot see.

**Never inspect `/app/output` with your own commands** (cat, sed, ls, python on result.json, edit_record.json, REPORT.md): every engine command prints what it found, `review` prints the claims, `verify` prints the final state. Each extra read costs 30-60 s of a 15-minute run.

## Rules for this task

- The model's fit statistics (e.g. Fisher's C, df, p) and its sample size (n and which analyses use it) are visible on the figure. When the prose and the table disagree (counts of significant paths, a p value, the sign of an estimate versus its test statistic), the figure follows the table and a visible footnote gives both versions.
- Must-show facts must be readable ON the figure (node note, edge label, text item or footnote), each with its comparator, unit and n; caption or result.json alone does not count. They stay visible in the edited version too. State factor levels and replicates in words ("control / treated, n = 3 per cell"), not as "2x3x3". A null result the order names (no interaction, n.s.) is written out.
- Entities first (with level: system > part > component), then relations in small batches (source, type, target, condition, passage); what the source excludes goes to `omitted`. Groups express containment or stage; put a node in a group only if the source says it belongs there.
- Distinguish in the edge `type`: containment (`contains`), order (`flow`), dependency (`dependency`), causal effect (`causal`, only if the source establishes it), fitted model path (`path`, with the estimate as label and `"edge_width"` when strength must be shown), undirected/correlated `association`, `comparison`, feedback (`return`), `evidence`. The legend is generated from the types you use.
- Siblings get the same `rank`. Decisions: kind `decision` with the condition as edge label on each outgoing edge. Loops: one edge of type `return` with its stop condition as label.
- Usually one diagram panel; add a text panel for definitions/limits, a chart panel if data are supplied. Sub-panels get ids A, B, C.
- Quantities on nodes or edges: unit and condition in `note`/label; sizes are not encoded, so say "not to scale".

- Group order in the work order is binding: "left to right" -> `"direction":"LR"`, "top to bottom" -> `"TB"`, groups listed in that order (an explicit direction is never overridden).

## How this works

You write small text files in `/app/work`. The bundled engine does layout, routing, drawing, SVG/PNG/PDF export, read-back checks, citations and the complete `/app/output/result.json`. Do not write your own SVG, matplotlib, export or JSON-assembly code, and do not read the engine source or example files.

`S=/skills/weekly-skill/scripts` (use the directory this SKILL.md is in if it differs).

**Hard limit: one response (thinking + text + tool call) over 16384 tokens aborts the whole run with nothing further saved.** Decide at most 6 nodes or 6 relations per response, write them, go on.

| step | command | calls |
|---|---|---|
| 1 | `python3 $S/figkit.py start schematic` - **the first command, before opening any material file**: indexes the material, drafts `/app/work/spec.json` (canvas, panels, groups) from the work order and prints item 1 with its passages. You may `cat /input/task.md` and the work order; do not open the paper: each item brings its passages | 1 |
| 2 | per item: ONE command that appends this item's lines (at most 6 + 6) to `A.nodes`, `A.edges` in `/app/work`, then `python3 $S/figkit.py build && python3 $S/figkit.py next`. Repeat until ALL ITEMS VISITED. `find WORD` / `show P012-P014` / `table FILE` only for a named missing fact. Relations that come from table rows are never typed: `python3 $S/figkit.py fromtable "Table 2" --where "p<0.1" --dash "p>=0.05"` (or a csv; limits as in the order; `--from N --to N --value N --p N` if columns are not found) writes nodes, values, signs and row sources; then write `A.place` (`id | group` per node). | 6-9 |
| 3 | `python3 $S/figkit.py audit`; real conflicts and limits: `set unresolved "item \| conflict \| both values \| P008,P021"` and a line in `notes.items` (visible footnote) when a reader needs it; `set title "..."`, `set caption "..."`; `build` | 1-2 |
| + | **`python3 $S/figkit.py review`** after the content is complete - prints every claim next to the sentence it cites and the whole requirement list: correct wrong direction, sign, strength, condition, unit or citation; add every missing required item (use `show`/`table` to fetch it). It ends with POSSIBLY MISSING lines: close every real gap, rebuild, review again. Accuracy and completeness weigh far more than speed; watch the printed minutes: requested edit done by minute 6, verify by minute 8 (cut at 15; the model may be slow) | 1-3 |
| 4 | requested edit, once (Editing below), then `python3 $S/figkit.py build --revise "what and why"`. Links to remove by p: `python3 $S/figkit.py prune "p>=0.05" --title "Links removed ..."` deletes them, lists them in a grey inset and sets edit_scope. Supplied SVG: `svgtree` + `edit` | 1-3 |
| 5 | `read_image /app/output/figure.png` once (skip if that tool is missing); correct what a reader would misread | 1-2 |
| 6 | `python3 $S/figkit.py verify`, then stop. Be here by minute 8: the run is cut at minute 15 | 1 |

Line files (one item per line, fields separated by `|`, so no `|` inside a field; `-` for empty). Extra `key=value` fields (`rank=2`, `layer=perturbation_X`, `step=3`, `value=-0.41`, `dash=dotted`) come only after all listed fields are filled: 8 for nodes, 7 for edges; placed earlier they are read as note or evidence text.

Text, timeline and footnote lines work the same way: `Q.items` / `C.items` (panel id): `value | text | src` (value `-` for a plain bullet); `notes.items` (footnotes): `- | text | src`; `T.items` (timeline panel T): `- | text | src | lane | start | end | at` (start and end for a period, or at = 1,3,7 for time points).

```
A.groups:  id | label | kind (membrane or -) | src
A.nodes:   id | label | kind | group | src | note | certainty | glyph
A.edges:   from | to | type | label | certainty | src | evidence (panel, cell line, perturbation)
```

Example: `K | Kinase K | enzyme | cyt | P004 | - | stated | - | rank=2` and `K | g | path | -0.41 | stated | P005,P009 | Table 2 row 3 | value=-0.41`.

Change or remove by appending lines: a node/group line with the same id replaces the earlier one; `id | delete` removes a node (delete its relations first). `from | to | type | delete` removes every relation of that pair and type (the type must match, or nothing happens). A relation is NOT replaced by a new label: append its `delete` line, then the new line. Two rows with the same pair, type and label become one, so give them different labels. Follow the NEXT line each command prints. Have the first build before minute 4. Stop only after a review shows no real gap; do not polish appearance further, and inspect files only with the commands given here.

## Every link of a table

`fromtable` reports rows drawn, rows not passing and rows without a result; the three must add up to the table. Put the inclusion rule into `set decision "..."`, the excluded rows into `set omitted "rows ... | reason"`, rows without a result (e.g. left out of a submodel) into a visible footnote. A node that gets no group is drawn outside the columns: assign all of them in `A.place`. Add entities the order names but no row connects as `A.nodes` lines. Without a usable table: 6 rows per response in table order, `src` = the row's passage or `file.csv#ROW`.

## Decide the science before drawing

1. Note from the work order: must-show items, forbidden claims, sizes/formats, language, the edit request.
2. For each candidate arrow ask: does a passage state this relation, with this direction, under this condition? Stated or observed -> `"certainty":"stated"`. Proposed, hypothesised, "may", "suggests", theoretical -> `"certainty":"proposed"` (drawn dashed, legend added automatically). A row of a fitted-model results table -> `path`, `stated`, never worded as a cause. Correlation -> type `association` (no arrowhead). Not supported -> leave it out and list it in `omitted` or `unresolved`.
3. Numbers: copy exactly as printed, with unit, n and meaning of the +/-. If text and table disagree, show neither silently: use the table value, and record both in `unresolved`.
4. Before finishing, go through the `audit` leads once: every real conflict or gap that touches the figure (text vs table, n, signs, units, missing facts) becomes one `unresolved` entry with both values and passages. "Not significant" never becomes "no effect" or "equal". "Not reported" stays "not reported".
5. Every node, edge, chart and text item needs `src`: passage ids (`"P012"`, `["P012","P015"]`), a data file (`"file.csv"` or `"file.csv#3-9"`), or `"workorder"`. Cite the passage that states that exact fact; the engine searches every printed number in it.

## spec.json

Diagram panels may carry `nodes`/`edges`/`groups` inline (as below, for small diagrams of up to 8 nodes) or in the line files above (preferred).

```json
{"title":"One-sentence claim the evidence supports","title_src":"P001",
 "canvas":{"width_mm":180,"font_pt":8,"dpi":300,"formats":[]},
 "layout":[["A"],["B","C"]],
 "panels":[
  {"id":"A","type":"diagram","title":"...","direction":"auto","src":"P003",
   "groups":[{"id":"cyt","label":"Cytoplasm","src":"P004"},{"id":"mem","label":"Plasma membrane","kind":"membrane"}],
   "nodes":[{"id":"K","label":"Kinase K","kind":"enzyme","group":"cyt","note":"pT202 form","src":"P004"},
            {"id":"g","label":"*geneA*","kind":"gene","glyph":"dna","src":"P005"}],
   "edges":[{"from":"K","to":"g","type":"activation","label":"in hypoxia","certainty":"stated","src":"P005"}]},
  {"id":"B","type":"chart","chart":"bar","title":"...","data":"values.csv","x":"dose","y":"mean","group":"arm",
   "err":"sd","err_meaning":"SD, n = 5","xlabel":"Dose (mg)","ylabel":"Signal (a.u.)","where":{"day":["7"]},
   "src":["values.csv","P009"],"weight":1.4},
  {"id":"C","type":"text","title":"...","items":[{"value":"2.8 nm","text":"mean pore size","src":"P010"},{"text":"Not tested in vivo","src":"P014"}]}],
 "caption":"Panels, abbreviations, n, error definition, what dashed means, not to scale.",
 "footnotes":[{"text":"Schematic, not to scale.","src":"workorder"}],
 "unresolved":[{"item":"...","state":"conflict|not reported|ambiguous|needs human confirmation","detail":"both values","src":["P008","P021"]}],
 "omitted":[{"item":"...","reason":"..."}],
 "decisions":["why this encoding/layout"]}
```

- `canvas`: exact page `"size_mm":[180,100]` (or `"size_px":[1600,1000]`) and smallest allowed text `"min_font_pt":7` when the work order gives them; extra export formats in `formats` (tiff, jpg, eps).
- node `kind`: protein receptor enzyme complex gene mrna small_molecule metabolite ion drug cell organism tissue phenotype process step equipment instrument sample material data software model decision milestone question result conclusion limitation concept
- edge `type`: activation inhibition binding phosphorylation modification transport expression conversion flow material gas liquid energy signal data control return waste dependency causal path association comparison evidence contains assembly (add `"bidirectional":true` if stated)
- optional node keys: `note` (second, smaller line), `step` (number), `rank` (column/row index), `emphasis`, `certainty`, `glyph` (optional icon, e.g. cell dna protein mouse brain plant flask microscope chip database chart gear target; full list in `references/guide.md`)
- evidence status of nodes/edges, `certainty`: `stated`/`observed` (solid), `cited` (grey: from other literature), `proposed` (dashed). Extra per-edge record: `"evidence":{"panel":"Fig 3B","cell_line":"...","perturbation":"..."}` (goes to content_map and `edge_table.csv`). Style overrides when the work order defines its own encoding: edge `width`, `dash` (solid dashed dotted), `color`, `double`; panel `"edge_width":{"field":"value","label":"|path coefficient|","max":0.8}` maps each edge's `value` to line width and sign to colour with an automatic legend; spec `"legend_extra":[{"text":"p < 0.05","dash":"solid","width":3}]`, `"legend_labels":{"activation":"..."}`.
- named overlay: nodes/edges with `"layer":"perturbation_X"` form the SVG group `layer-perturbation_X`.
- charts: `"chart":"bar|stacked|line|scatter|dot|box|heatmap|forest"`, options in `references/charts.md` (read it for anything beyond a plain chart).
- Schedule, dosing plan, sampling days or phases: a real time axis, `{"id":"T","type":"timeline","title":"Schedule","unit":"day","items":[{"lane":"Phase","start":0,"end":7,"text":"Preparation","src":"P010"},{"lane":"Sampling","at":[1,3,7],"text":"pH, nitrate","src":"P012"}]}` (bars for periods, diamonds for time points, one lane per topic; a change of method or condition is its own bar).
- text markup everywhere: `*italic*`, `_{sub}`, `^{sup}`. Gene symbols italic, proteins upright, as in the source.
- Labels: about 1-5 words; conditions go on the edge label or `note`; explanation goes to the caption. 6-18 nodes per diagram unless all rows are requested. Panels in one `layout` row share width by `weight`; `[["A",["B","C"]]]` puts B above C to the right of A.

## Editing so that everything else is preserved

- Figure you built (always use this route for it, never `edit`): edit only the affected entries, add `"edit_scope":["id fragment", ...]` (element ids that may change, e.g. `"node-ZK1"`, `"layer-perturbation_X"`, `"A-edge-K-"`) and/or `"edit_protect":["B-"]` (ids that must not change), then `build --revise "..."`. The first version is frozen as `figure_before_edit.*`; every later `--revise` is compared with it. After the first `--revise` use only `--revise`; `build --restart` discards the edit and starts a new v1.
- Prepare v1: the page must not change size in the edit. Read `BUILT ... W x H mm` and, unless the work order fixes the page or its maximum height, set `"size_mm":[W,H+15]` (H+45 if the edit adds a text panel), build plainly once, then start the edit. With one diagram panel put added text in a footnote: a second panel re-frames and moves the diagram (or have a text panel in v1 already). With `edge_width` set `"max"` to the largest |value|, else removing the strongest link rescales all others.
- Remove links: one `from | to | type | delete` line each (inline spec: delete the entry; never retype or reorder other lines). List in `edit_scope` each `"A-edge-FROM-type-TO"` plus the containers `"A-edges"`, and `"A-edge-labels"` / `"A-nodes"` if labels / nodes go. A node left without links stays unless the request removes it. Confirm with the counting command that exactly the requested links are gone. Other edits work the same.
- Unaffected entities and connectors keep their geometry; `edit_record.json` holds changed/added/removed ids, the byte-identical count and rollback.
- SVG supplied by the case: `svgtree FILE.svg`, then `/app/work/ops.json` = `{"ops":[{"id":"label_3","op":"text","old":"5 mM","value":"5 uM","reason":"...","src":"P007"},{"id":"bar2","op":"attr","set":{"fill":"#0072B2"}},{"id":"grp","op":"remove|insert_after|insert_before|replace","svg":"<g .../>"}]}` and `python3 $S/figkit.py edit FILE.svg /app/work/ops.json --reason "..."`. Put extra `content_map`, `exceptions` or `allowed_ids` in `/app/work/edit_meta.json` before running. Elements outside the ops stay byte-identical.

## If something goes wrong

- `SPEC ERRORS` / `CANNOT DRAW`: nothing was overwritten; fix the named entry.
- `layout_collisions`: shorten labels, set `"direction":"LR"`, `"TB"` or `"WRAP"` (long numbered routes), move detail to `note`/caption, or split the panel.
- too tall: panels side by side in `layout`, LR, or cut nodes no must-show item needs.
- `numbers_traceable`: cite the passage that has the number, or correct it; if it is computed, say so in the label and in `decisions` with the formula.
- `source_preserving_edit`: an unintended id changed -> undo that line; only a container or the requested id -> add it to `edit_scope`; "page could not hold" -> page size changed, see "Prepare v1" (plain build of v1 with more height, then repeat).
- `pdf_export` with fonts or labels: replace unusual symbols once (`_{}`/`^{}`), else leave it disclosed.
- no work order file: take the requirements from task.md and case.json, cite `task`.
- unreadable PDF/image or missing data: record it in `unresolved` with what you tried; never fill the gap from memory.
- No exporter works: SVG and result.json stay valid; status becomes partial.

`result.json` is written by the engine with the contract fields; do not rewrite it. Extra root fields in a case contract: load, set and save it with a few lines of Python after the last build.

See `references/guide.md` for usage, method, limits and maintenance (section 10: table rows to edges to removal edit, fictional data), and `examples/synthetic` for a complete input and spec (`python3 $S/figkit.py selftest`). Same-input comparison with and without this Skill on local practice cases: `references/evidence.md` (not needed during a run).
