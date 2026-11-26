---
name: apparatus-technical-route
description: Draw or edit experimental apparatus diagrams and technical route / protocol / roadmap figures from supplied methods, with parts, interfaces, numbered steps, branches, loops and separate material, energy and signal flows, editable SVG, PNG/PDF, source map and result.json. Use for any apparatus, workflow or technical route figure task whose input is in /input with a figure-workorder.
---

# Experimental apparatus and technical route diagram

Use when the task is an apparatus, a process flow or a technical route. Someone should be able to count the parts, follow each line and execute the steps in order.

**Do not read the paper up front** (no cat, grep or python on material.json, PDFs or text files). Runs that did used 6-12 of their 15 minutes before the first drawing and lost the edit. `start` and `next` select the passages for every requirement; open one more passage with `show` only when an item names a fact you cannot see.

## Rules for this task

- Must-show facts must be readable ON the figure (node note, edge label, text item or footnote), each with its comparator, unit and n; caption or result.json alone does not count. They stay visible in the edited version too. State factor levels and replicates in words ("control / treated, n = 3 per cell"), not as "2x3x3". A null result the order names (no interaction, n.s.) is written out.
- Hardware and procedure both requested: two panels, `A` apparatus (kind equipment/instrument/sample/material with `glyph`, one node per physical part, quantity in the label: "Thermocouple x2") and `B` route (kind step with `step` numbers, decision, milestone). Layout `[["A"],["B"]]`.
- Size: at most about 14 apparatus nodes and 14 route steps when the page size is fixed; on a page near 200 x 140 mm stay near 10 + 10. Over that, merge consecutive actions of the same phase into one step and identical parts into one "x2" node unless the source splits a stream between them (say so in `decisions`); never drop an inline unit.
- In a panel with groups give every node a group. Groups are subsystems (supply, reaction zone, detection) or phases; if the order wants a time axis or sampling days, add a `timeline` panel as the last row (it replaces day labels scattered over steps).
- Line types: material/gas/liquid, energy, signal/data/control are different; never mix them in one line. Joints: `assembly`. A leaving stream with no stated destination: node "not specified" plus an `unresolved` entry.
- Design splits are drawn as splits: treatment first, then the sub-branches inside each treatment, with n on every branch. Dosing nodes carry reagent, concentration and amount per addition; a change of analytical method carries its days and its limit.
- Recirculating water, gas or material keeps its own type (`liquid`, `gas`, `material`) all the way round; `return` is for procedure loops (repeat, recycle step). A point of entry or exit the source does not name is not drawn as stated: node "entry not specified" or a footnote. Control or untreated branches bypass the treatment steps and rejoin at the common sampling.
- One unit with two names in the source = one node; name the alias in a visible footnote ("X = Y in the text"); volumes that do not add up to the printed total: visible footnote plus `unresolved`.
- Steps: parameters (temperature, time, rate, n) exactly as given in `note`. Parallel steps: 4a/4b from the same predecessor (they align by themselves). Decisions show both outcomes; loops go back with `return`, label = stop condition or number of cycles.
- Never move a value from one run, step or instrument to another. Missing dimension/model/flow rate: "not reported" in `unresolved`, no guess on the drawing.
- Footnote "Schematic, not to scale." unless calibrated dimensions are supplied.

### Trace each flow, sentence by sentence

The usual error here is an invented shortcut: the text says X goes through Y to Z and the drawing shows X to Z. So, before any apparatus edge:

1. `find` flow words one by one (through, via, into, returned, pumped, outlet, drain, between) and `show` those passages.
2. For each sentence write the chain as a comment in `A.edges`, then one edge per `>`, in the same order: `# P003: reactor > condenser > pump > reactor`. Only neighbours in a chain may be joined. "Between" / "in line" means one line in and one line out.
3. A split is several edges from one unit, a merge several into one. Arrow = real flow direction. A closed loop must come back to its first unit: walk it once edge by edge. Type of the closing edge: `return`, or the medium type if the work order fixes the line style.
4. Order of two units not stated: join only what is stated; the rest goes to `unresolved`. Pump position, valve, sensor or controller not in the text: not drawn.
5. `NOTE ... flow continuity`: reread the sentence of that unit. An end point (trap, analyser) may stay without outlet.

Example (invented; shows format only, parts of the files):

```
cat >> /app/work/A.nodes <<'EOF'
rx | Reactor | equipment | loop | P003 | 2 L | stated | vessel
cond | Condenser | equipment | loop | P003 | - | stated | column
pump | Pump | equipment | loop | P003 | - | stated | pump
EOF
cat >> /app/work/A.edges <<'EOF'
# P003: reactor > condenser > pump > reactor
rx | cond | gas | - | stated | P003
cond | pump | gas | - | stated | P003
pump | rx | return | recirculated | stated | P003
EOF
cat >> /app/work/B.nodes <<'EOF'
s2 | Purge | step | prep | P005 | 30 min | stated | - | step=2
d1 | O_{2} < 0.1%? | decision | prep | P005 | - | stated
s3 | Start run | step | run | P006 | 4 h | stated | - | step=3
s4a | Light | step | run | P006 | n = 3 | stated | - | step=4a
s4b | Dark | step | run | P006 | n = 3 | stated | - | step=4b
EOF
cat >> /app/work/B.edges <<'EOF'
s2 | d1 | flow | - | stated | P005
d1 | s2 | return | no: repeat | stated | P005
d1 | s3 | flow | yes | stated | P005
s3 | s4a | flow | - | stated | P006
s3 | s4b | flow | - | stated | P006
EOF
```

## How this works

You write small text files in `/app/work`. The bundled engine does layout, routing, drawing, SVG/PNG/PDF export, read-back checks, citations and a complete `/app/output/result.json`. Do not write your own SVG, matplotlib, export or JSON-assembly code, and do not read the engine source or example files: all you need is on this page, and reading code eats the budget.

`S=/skills/weekly-skill/scripts` (use the directory this SKILL.md is in if it differs).

**Hard limit: one response (thinking + text + tool call) over 16384 tokens aborts the whole run with nothing further saved.** This is the most common failure. Never think the whole figure through at once: decide at most 6 nodes or 6 relations per response, write them, go on. Corrections are cheap; a dead run is not.

| step | command | calls |
|---|---|---|
| 1 | `python3 $S/figkit.py start apparatus` - **the first command, before opening any material file**: indexes the material, drafts `/app/work/spec.json` (canvas, panels) from the work order and prints item 1 with its passages. You may `cat /input/task.md` and the work order; do not open the paper: each item brings its passages | 1 |
| 2 | per item: ONE command that appends this item's lines (at most 6 + 6) to `A.groups`, `A.nodes`, `A.edges` (hardware), `B.groups`, `B.nodes`, `B.edges` (route), `T.items` (schedule) in `/app/work`, then `python3 $S/figkit.py build && python3 $S/figkit.py next`. Repeat until ALL ITEMS VISITED. `find WORD` / `show P012-P014` / `table FILE` only for a named missing fact. | 6-9 |
| 3 | `python3 $S/figkit.py audit`; real conflicts and limits: `set unresolved "item \| conflict \| both values \| P008,P021"` and a line in `notes.items` (visible footnote) when a reader needs it; `set title "..."`, `set caption "..."`; `build` | 1-2 |
| + | **`python3 $S/figkit.py review`** after the content is complete - prints every claim next to the sentence it cites and the whole requirement list: correct wrong direction, sign, strength, condition, unit or citation; add every missing required item (use `show`/`table` to fetch it). It ends with POSSIBLY MISSING lines: close every real gap, rebuild, review again. Accuracy and completeness weigh far more than speed; watch the printed minutes: requested edit done by minute 6, verify by minute 8 (cut at 15; the model may be slow) | 1-3 |
| 4 | requested edit, once: change lines/spec, set edit_scope (Editing below), `python3 $S/figkit.py build --revise "what and why"`; supplied SVG: `svgtree` + `edit` | 1-3 |
| 5 | `read_image /app/output/figure.png` once (skip if you have no image tool); correct what a reader would misread | 1-2 |
| 6 | `python3 $S/figkit.py verify`, then stop. Be here by minute 8: the run is cut at minute 15 | 1 |

Line files: one item per line, fields separated by `|`, `-` for empty. A later node/group line with the same id replaces the earlier one. To correct a relation write `from | to | type | delete` with the old type, then the new line. `#` starts a comment. Extra `key=value` fields (`step=3`, `layer=x`, `color=#8B5A2B`, `dash=dotted`) come only AFTER all 8 node fields or all 7 edge fields; in an earlier field they are misread.

Text, timeline and footnote lines work the same way: `Q.items` / `C.items` (panel id): `value | text | src` (value `-` for a plain bullet); `notes.items` (footnotes): `- | text | src`; `T.items` (timeline panel T): `- | text | src | lane | start | end | at` (start and end for a period, or at = 1,3,7 for time points).

```
A.groups:  id | label | kind (membrane or -) | src
A.nodes:   id | label | kind | group | src | note | certainty | glyph
A.edges:   from | to | type | label | certainty | src | evidence
```

Follow the NEXT line each command prints. Have the first build before minute 4. After any build the deliverables are complete, so an interruption never leaves an empty output. Stop only after a review shows no real gap; do not polish appearance further and do not inspect files with your own scripts.

## Decide the science before drawing

1. Copy from the work order into your head: must-show items, forbidden claims, required sizes/formats, language, the edit request.
2. For each candidate arrow ask: does a passage state this relation, with this direction, under this condition? Stated or observed -> `"certainty":"stated"`. Proposed, "may", "suggests" -> `"certainty":"proposed"` (drawn dashed, legend added automatically). Not supported -> leave it out and list it in `omitted` or `unresolved`.
3. Numbers: copy exactly as printed, with unit, n and meaning of the +/-. If text and table disagree, show neither silently: use the table value, and record both in `unresolved`.
4. Before finishing, go through the `audit` leads once: every real conflict or gap that touches the product (text vs table, n, dates, units, aliases, missing facts) becomes one `unresolved` entry with both values and passages. "Not significant" never becomes "no effect".
5. Every node, edge, chart and text item needs `src`: passage ids (`"P012"`, `["P012","P015"]`), a data file (`"file.csv"` or `"file.csv#3-9"`), or `"workorder"`. Cite the passage that states that exact fact. The engine searches every printed number in the cited source and reports those it cannot find.

## spec.json

```json
{"title":"What the figure shows","title_src":"P001",
 "canvas":{"size_mm":[180,140],"font_pt":8,"dpi":300,"formats":[]},
 "layout":[["A"],["B"]],
 "panels":[{"id":"A","type":"diagram","title":"Apparatus","src":"P003"},
  {"id":"B","type":"diagram","title":"Technical route","src":"P005"}],
 "caption":"Self-contained: panels, abbreviations, n, what each line style means, not to scale.",
 "footnotes":[{"text":"Schematic, not to scale.","src":"workorder"}],
 "unresolved":[{"item":"...","state":"conflict|not reported|ambiguous","detail":"both values","src":["P008","P021"]}],
 "omitted":[{"item":"...","reason":"..."}],
 "decisions":["why this encoding/layout"]}
```

- Optional text panel: `{"id":"C","type":"text","title":"...","items":[{"value":"2.8 nm","text":"pore size","src":"P010"}]}`.
- `canvas`: without a fixed page use `"width_mm":180` instead of `size_mm` (or `"size_px":[1600,1000]`) and smallest allowed text `"min_font_pt":7` when the work order gives it; extra export formats in `formats` (tiff, jpg, eps).
- node `kind`: equipment instrument sample material data step process decision milestone software model cell organism tissue small_molecule drug result conclusion limitation concept
- edge `type`: material gas liquid energy signal data control return waste flow assembly contains dependency conversion transport association comparison evidence activation inhibition (add `"bidirectional":true` if stated)
- optional node keys: `note` (second, smaller line), `step` (number), `rank` (column index inside its group, from 0; rarely needed), `emphasis`, `certainty`, `glyph` (cell bacteria virus dna protein antibody mouse human group brain heart lung plant leaf beaker flask tube dish syringe pill microscope laser lens mirror detector camera furnace heater pump valve cylinder vessel column electrode battery chip computer database document network chart curve gear clock thermometer magnet wave crystal molecule droplet globe satellite robot check question target warning)
- evidence status of nodes/edges, `certainty`: `stated`/`observed` (solid), `cited` (grey: from other literature), `proposed` (dashed). Style overrides: edge `width`, `dash` (solid dashed dotted), `color`; spec `"legend_labels":{"liquid":"Water"}` renames an automatic legend entry. The automatic legend shows built-in type colours (liquid blue solid, gas green, energy orange dash-dot, signal/data purple dotted, waste/return olive dashed): if the work order fixes other colours, set `color`/`dash` on every edge of that type, set `"legend":false` and add a text panel "Line key" last, one item per line style (`{"value":"- -","color":"#C9A100","text":"air / light","src":"workorder"}`), decision and dashed-line meaning included.
- charts only if requested: read `references/charts.md` first.
- Schedule, dosing plan, sampling days or phases: a real time axis, `{"id":"T","type":"timeline","title":"Schedule","unit":"day","items":[{"lane":"Phase","start":0,"end":7,"text":"Preparation","src":"P010"},{"lane":"Sampling","at":[1,3,7],"text":"pH, nitrate","src":"P012"}]}` (bars for periods, diamonds for time points, one lane per topic; a change of method or condition is its own bar).
- text markup everywhere: `*italic*`, `_{sub}`, `^{sup}`.
- Keep labels short (about 1-5 words); conditions go on the edge label or `note`; explanation goes to the caption. Panels in one row share width by `weight`.

## Editing so that everything else is preserved

- Figure you built (always this route, never `edit`). Edit only the affected spec entries, add `"edit_scope":["id fragment", ...]` (element ids that may change, e.g. `"node-trap"`, `"A-edge-cond-liquid-trap"`, and the group of a node whose label gets longer, `"A-group-loop"`) and/or `"edit_protect":["B-"]` (ids that must not change), then `build --revise "..."`. The first version is frozen as `figure_before_edit.*`; every later `--revise` is compared with it (`build --restart` discards the edit and starts a new v1). Added text = a `text` panel at the end or a footnote, so nothing above moves. Change only what was asked, keep title and caption unless they become wrong. Before/after files, changed ids, byte-identical count and rollback go to `edit_record.json`.
- SVG supplied by the case: `svgtree FILE.svg`, then `/app/work/ops.json` = `{"ops":[{"id":"label_3","op":"text","old":"5 mM","value":"5 uM","reason":"...","src":"P007"},{"id":"bar2","op":"attr","set":{"fill":"#0072B2"}},{"id":"grp","op":"remove|insert_after|insert_before|replace","svg":"<g .../>"}]}` and `python3 $S/figkit.py edit FILE.svg /app/work/ops.json --reason "..."`. Put extra `content_map`, `exceptions` or `allowed_ids` in `/app/work/edit_meta.json` before running. Elements outside the ops stay byte-identical.

## If something goes wrong

- `SPEC ERRORS` / `CANNOT DRAW`: nothing was overwritten; fix the named entry.
- Two passages disagree about a connection or value: draw the version of the more specific passage with certainty `proposed`; both versions go to `unresolved` (state `conflict`). Ambiguous wording: state `ambiguous`, no extra line.
- `minimum_type_size` (page too full): check that every node has a group, drop notes and edge labels that only repeat, merge steps; once, then accept the disclosed result.
- `layout_collisions`: shorten labels, set `"direction":"LR"`, `"TB"` or `"WRAP"` (long numbered routes), move detail to `note`/caption, or split the panel.
- too tall: use LR, or cut nodes that no must-show item needs.
- `numbers_traceable`: cite the passage that has the number, or correct it; if it is computed, say so in the label and in `decisions` with the formula.
- unreadable PDF/image or missing data: record it in `unresolved` with what you tried; never fill the gap from memory.
- No exporter works: the SVG and result.json are still valid; status becomes partial and says so.

`result.json` is written by the engine with the contract fields; do not rewrite it. If a case contract has extra root fields, add them with a few lines of Python that load, set and save the file after the last build.

See `references/guide.md` for usage, method, limits and maintenance, `references/example-apparatus-route.md` for a complete example (for people, not needed at run time) and `examples/synthetic` for the selftest input (`python3 $S/figkit.py selftest`). Same-input comparison with and without this Skill on local practice cases: `references/evidence.md` (not needed during a run).
