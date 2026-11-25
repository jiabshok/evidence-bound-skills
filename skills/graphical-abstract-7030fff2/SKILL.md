---
name: graphical-abstract
description: Make or revise a single-page graphical abstract (图形摘要 - question, method, key result, conclusion) from supplied papers, records or tables, with editable SVG, PNG/PDF exports, per-element sources, checks and result.json. Use for any figure task whose input is in /input with a figure-workorder.
---

# Graphical abstract from source to editable figure

A reader must get question -> method -> key result -> conclusion in one look; a reviewer must trace each element to its source.

## Rules for this task

- Must-show facts must be readable ON the figure (node note, edge label, text item or footnote), each with its comparator, unit and n; caption or result.json alone does not count. They stay visible in the edited version too. State factor levels and replicates in words ("control / treated, n = 3 per cell"), not as "2x3x3". A null result the order names (no interaction, n.s.) is written out.
- Panels (the work order overrides names and number): `Q` question/gap, `M` design, `R` (and `R2`, `R3`) key results, `C` conclusion and limits, numbered in reading order ("1 Question", "2 Design", "3a ...", "3b ...", "4 Conclusion and limits"). Leave `layout` out: the engine arranges the panels in reading order and fills the page. If the order is to edit a supplied SVG, keep its structure and use the `edit` route.
- Item lines (`Q.items`, `M.items`, `C.items`): `value | text | src`. Special `value`s: `-` bullet; `key` the one-sentence message in bold; `label:Site` run-in label (Site, When, Sample, Factors, Measured ...); `grid` a crossed or grouped design drawn as squares: `grid | rows treated, control; cols 0 mM, 5 mM; n 3 | P017`; `box:Scope` a framed list, entries separated by `;`; `ns` a framed "Not significant" list, entries separated by `;`, each with response and p; any number with unit (`+69%`) is set large.
- `M` is text by default (label lines: site, when from-to, n and replicates, factors with every level, what was measured; plus `grid` for a factorial or group design). Use a `diagram` (`M.nodes`, `M.edges` with glyphs) instead when the method is a process or mechanism.
- `R`/`R2`: one small chart per distinct response (`R.panel.json`, `R2.panel.json`), e.g. `{"type":"chart","title":"3a Dose: yield","chart":"bar","inline":{"columns":["level","mean","err"],"rows":[["0 mM",4.1,0.5]]},"x":"level","y":"mean","err":"err","err_meaning":"reported error","value_labels":true,"xlabel":"","ylabel":"Yield (g m-2)","color":"#0072B2","note":"Mean +/- reported error; n = 6 per level; p < 0.001","src":["P031"]}`. A different `color` per response. Name the error type only if the source names it for these values; n is the replication behind each mean, not the whole experiment. Never draw bars for numbers that were not supplied.
- `C`: `key` line (what, direction, size, comparator), `ns` box with every non-significant effect or interaction the order or paper names, `box:Scope` (season or period, site, scale, what was not measured, what is extrapolated). Full place and period names once ("month-month year", region and country), never "one year" for one season.
- `set subtitle "system; place; period"` fills the title band. After the edit, values that were must-show before must still be readable (a short chart note of at most two lines, or a `C` box); do not change other panels.
- Landscape is preferred: aim for a height of at most 0.75 of the width unless the work order fixes a size. Total visible text about 90-140 words: a missing must-show fact costs more than small type, so add all of them first and shorten wording second.
- `value` in a text item is a number with unit (at most 10 characters, e.g. "+69%"); words go to `text`. Each `text` at most 14 words. If numbers for `R` are only printed in the text or a table, use `"inline"` data with `src`.

## How this works

You write small text files in `/app/work`. The bundled engine does layout, routing, drawing, SVG/PNG/PDF export, read-back checks, citations and a complete `/app/output/result.json`. Do not write your own SVG, matplotlib, export or JSON-assembly code, and do not read the engine source, guide or examples during a run: everything needed is on this page.

`S=/skills/weekly-skill/scripts` (use the directory this SKILL.md is in if it differs).

**Hard limit: one response (thinking + text + tool call) over 16384 tokens aborts the whole run with nothing further saved.** Never think the whole figure through at once: decide at most 6 nodes or 6 relations per response, write them, go on.

| step | command | calls |
|---|---|---|
| 1 | `python3 $S/figkit.py start abstract` - **the first command, before opening any material file**: indexes the material, drafts `/app/work/spec.json` (canvas, panels) from the work order and prints item 1 with its passages. You may `cat /input/task.md` and the work order; do not open the paper: each item brings its passages | 1 |
| 2 | per item: ONE command that appends this item's lines (at most 6 + 6) to `Q.items`, `M.items`, `C.items`, `R.panel.json` / `R2.panel.json` (charts), `notes.items` in `/app/work`, then `python3 $S/figkit.py build && python3 $S/figkit.py next`. Repeat until ALL ITEMS VISITED. `find WORD` / `show P012-P014` / `table FILE` only for a named missing fact. | 6-9 |
| 3 | `python3 $S/figkit.py audit`; real conflicts and limits: `set unresolved "item \| conflict \| both values \| P008,P021"` and a line in `notes.items` (visible footnote) when a reader needs it; `set title "..."`, `set caption "..."`; `build` | 1-2 |
| + | **`python3 $S/figkit.py review`** after the content is complete - prints every claim next to the sentence it cites and the whole requirement list: correct wrong direction, sign, strength, condition, unit or citation; add every missing required item (use `show`/`table` to fetch it). It ends with POSSIBLY MISSING lines: close every real gap, rebuild, review again. Accuracy and completeness weigh far more than speed; watch the printed minutes: requested edit done by minute 8, verify by minute 10 (cut at 15; the model may be slow) | 1-3 |
| 4 | requested edit, once: change lines/spec, set edit_scope (Editing below), `python3 $S/figkit.py build --revise "what and why"`; supplied SVG: `svgtree` + `edit` | 1-3 |
| 5 | `read_image /app/output/figure.png` once (no image tool: skip, say so in `decisions`); correct what a reader would misread (after the edit always `build --revise`) | 1-2 |
| 6 | `python3 $S/figkit.py verify`, then stop. Be here by minute 10: the run is cut at minute 15 | 1 |

Line files are named by panel id (an id not in the spec adds an unwanted panel): one item per line, fields separated by `|`, `-` for empty; a later node/group line with the same id replaces the earlier one; `from | to | type | delete` removes relations; extra `key=value` fields allowed at the end, e.g. `| rank=2`, `| layer=perturbation_X`, `| step=3`, `| value=-0.41`, `| dash=dotted`:

Text, timeline and footnote lines work the same way: `Q.items` / `C.items` (panel id): `value | text | src` (value `-` for a plain bullet); `notes.items` (footnotes): `- | text | src`; `T.items` (timeline panel T): `- | text | src | lane | start | end | at` (start and end for a period, or at = 1,3,7 for time points).

```
M.groups:  id | label | kind (membrane or -) | src
M.nodes:   id | label | kind | group | src | note | certainty | glyph
M.edges:   from | to | type | label | certainty | src | evidence (panel, cell line, perturbation)
```

Example: `K | Kinase K | enzyme | cyt | P004 | - | stated` and `K | g | activation | in hypoxia | proposed | P005,P009 | Fig 3B; HeLa; siRNA`. Follow the NEXT line each command prints. Have the first build before minute 4; after any build the deliverables are complete. Stop when the must-show items are present; do not polish or inspect files with your own scripts.

## Decide the science before drawing

1. List from the work order: must-show items, forbidden claims, required sizes/formats, language, the edit request.
2. For each candidate arrow ask: does a passage state this relation, with this direction, under this condition? Stated or observed -> `"certainty":"stated"`. Proposed, hypothesised, "may", "suggests", model-only -> `"certainty":"proposed"` (drawn dashed, legend added automatically). Correlation -> type `association` (no arrowhead). Not supported -> leave it out and list it in `omitted` or `unresolved`.
3. Numbers: copy exactly as printed, with unit, n and meaning of the +/-. If text and table disagree, show neither silently: use the table value, and record both in `unresolved`.
4. Before finishing, go through the `audit` leads once: every real conflict or gap that touches the product (text vs table, n per analysis, dates, signs, units, interactions, corrections, missing design facts) becomes one `unresolved` entry with both values and passages. "Not significant" never becomes "no effect" or "equal". "Not reported" stays "not reported".
5. Every node, edge, chart and text item needs `src`: passage ids (`"P012"`, `["P012","P015"]`), a data file (`"file.csv"` or `"file.csv#3-9"`), or `"workorder"`. Cite the passage that states that exact fact. The engine searches every printed number in the cited source and reports those it cannot find.

## spec.json

Diagram panels carry `nodes`/`edges`/`groups` inline (as below) or in line files (preferred; they replace inline ones).

```json
{"title":"One-sentence claim the evidence supports","title_src":"P001",
 "canvas":{"width_mm":180,"font_pt":8,"dpi":300,"formats":[]},
 "layout":[[["Q","M"],["R","C"]]],
 "panels":[
  {"id":"Q","type":"text","title":"1 Question","items":[{"text":"Does X change Y in Z?","src":"P003"}]},
  {"id":"M","type":"diagram","title":"2 Method","direction":"LR",
   "nodes":[{"id":"K","label":"Cells","kind":"cell","note":"n = 5","glyph":"cell","src":["P004","P009"]},
            {"id":"g","label":"*geneA* assay","kind":"instrument","glyph":"detector","src":"P005"}],
   "edges":[{"from":"K","to":"g","type":"data","label":"24 h","certainty":"stated","src":"P005"}]},
  {"id":"R","type":"chart","chart":"bar","title":"3 Key result","data":"values.csv","x":"dose","y":"mean","group":"arm",
   "err":"sd","err_meaning":"SD, n = 5","xlabel":"Dose (mg)","ylabel":"Signal (a.u.)","where":{"day":["7"]},
   "note":"Mean +/- SD, n = 5 animals","src":["values.csv","P009"],"weight":1.4},
  {"id":"C","type":"text","title":"4 Conclusion and limits","items":[{"value":"2.8 nm","text":"mean pore size","src":"P010"},{"text":"Not tested in vivo","src":"P014"}]}],
 "caption":"Self-contained caption: panels, abbreviations, n, error definition, what dashed means, not to scale.",
 "footnotes":[{"text":"Schematic, not to scale.","src":"workorder"}],
 "unresolved":[{"item":"...","state":"conflict|not reported|ambiguous|unreadable","detail":"both values","src":["P008","P021"]}],
 "omitted":[{"item":"...","reason":"..."}],
 "decisions":["why this encoding/layout","Human confirmation: none in this run; to confirm: ..."]}
```

- `canvas`: exact page `"size_mm":[180,100]` (or `"size_px":[1600,1000]`) and smallest allowed text `"min_font_pt":7` when the work order gives them; extra export formats in `formats` (tiff, jpg, eps).
- node `kind`: protein receptor enzyme complex gene mrna small_molecule metabolite ion drug cell organism tissue phenotype process step equipment instrument sample material data software model decision milestone question result conclusion limitation concept
- edge `type`: activation inhibition binding phosphorylation modification transport expression conversion flow material gas liquid energy signal data control return waste dependency causal path association comparison evidence contains assembly (add `"bidirectional":true` if stated)
- optional node keys: `note` (second, smaller line), `step` (number), `rank` (column/row index), `emphasis`, `certainty`, `glyph` (cell bacteria virus dna protein antibody mouse human group brain heart lung plant leaf beaker flask tube dish syringe pill microscope laser lens mirror detector camera furnace heater pump valve cylinder vessel column electrode battery chip computer database document network chart curve gear clock thermometer magnet wave crystal molecule droplet globe satellite robot check question target warning)
- evidence status of nodes/edges, `certainty`: `stated`/`observed` (solid), `cited` (grey: from other literature), `proposed` (dashed). Extra per-edge record: `"evidence":{"panel":"Fig 3B","cell_line":"...","perturbation":"..."}` (goes to content_map and `edge_table.csv`). Style overrides when the work order defines its own encoding: edge `width`, `dash` (solid dashed dotted), `color`, `double`; panel `"edge_width":{"field":"value","label":"|path coefficient|"}` maps each edge's `value` to line width and sign to colour with an automatic legend; spec `"legend_extra":[{"text":"p < 0.05","dash":"solid","width":3}]`, `"legend_labels":{"activation":"..."}`.
- named overlay: give nodes/edges `"layer":"perturbation_X"`; they are written as a separate SVG group `layer-perturbation_X`.
- chart types: bar stacked line scatter dot box (raw observations) heatmap (`x`,`y`,`value`) forest (`x`=label,`y`=estimate,`lo`,`hi`,`ref`). Set `group` equal to `x` to colour bars by category (same colours as that group in other panels). Data may be CSV, TSV, JSON records or `"book.xlsx!Sheet name"` (`@2` for its second table block). Keys: `where`, `group`, `order`, `group_order`, `labels` {raw: shown}, `err` or `lo`+`hi`, `err_meaning`, `yscale`/`xscale` "log", `ylim`, `value_labels`, `annotations` [{"y":0.05,"text":"threshold"}], `height_mm`.
- chart computations (never compute by hand): `"derive":{"ratio":"[Lum] / [OD600]"}` adds a column per row (+ - * / ** log10 log2 ln sqrt); `"reduce":{"by":["strain","culture"],"y":"ratio","fn":"max"}` (max min mean median sum count first last); `"stat":"mean_sd|mean_sem|mean_ci95|median_iqr|geomean_sd"` draws the summary of replicates (same x and group) plus every individual point. All drawn values, n and contributing rows go to `plotted_values.csv`. To plot y against a measured x per cell (e.g. mean value vs mean OD for each time point), add `"stat_by":["time"]`: cells are stat_by + group, x and y are both summarised and horizontal bars are drawn. Values that exist only as printed text: `"inline":{"columns":["site","mean","se"],"rows":[["A","1.2","0.3"]]}` instead of `data`, with `src` of the passages that print them. Horizontal errors: `xerr` or `xlo`+`xhi`.
- shared-axis `overlays` in a chart panel: [{"type":"line|points|ring","data":"other.csv","where":{...},"x":"..","y":"..","layer":"name","label":"..","dash":"dashed","color":"#444","label_col":"name"}, {"type":"abline","slope":0.73,"intercept":1.2,"space":"log10","label":"..."}, {"type":"hline","value":1,"label":".."}, {"type":"vline","value":3}]. `ring` without `data` circles rows of the main table chosen by `where`.
- Schedule, dosing plan, sampling days or phases: a real time axis, `{"id":"T","type":"timeline","title":"Schedule","unit":"day","items":[{"lane":"Phase","start":0,"end":7,"text":"Preparation","src":"P010"},{"lane":"Sampling","at":[1,3,7],"text":"pH, nitrate","src":"P012"}]}` (bars for periods, diamonds for time points, one lane per topic; a change of method or condition is its own bar).
- text markup everywhere: `*italic*`, `_{sub}`, `^{sup}`. Gene symbols italic, proteins upright, as in the source.
- Keep labels short (about 1-5 words); conditions go on the edge label or `note`; explanation goes to the caption. `M` 3-6 nodes, other diagrams at most 18. Panels in one row share width by `weight`; a nested list is a column.

## Editing so that everything else is preserved

- Figure you built (always use this route for it, never `edit`): edit only the affected spec entries, add `"edit_scope":["id fragment", ...]` (element ids that may change, e.g. `"node-ZK1"`, `"layer-perturbation_X"`, `"M-edge-K-"`) and/or `"edit_protect":["R","C"]` (panel ids without a dash, or full element ids, that must not change), then `build --revise "..."`. The first version is frozen as `figure_before_edit.*`; every later `--revise` is compared with it (a plain `build` starts a new v1; `--revise` keeps v1's canvas and layout). Removing an edge = delete it from the spec; adding text (an inset, a list, a note) = add a `text` panel at the end or a footnote, which is placed below so nothing above moves. Unaffected entities and connectors keep their geometry; before/after files, changed/added/removed ids, count of byte-identical elements and rollback are written to `edit_record.json`.
- SVG supplied by the case: `svgtree FILE.svg`, then `/app/work/ops.json` = `{"ops":[{"id":"label_3","op":"text","old":"5 mM","value":"5 uM","reason":"...","src":"P007"},{"id":"bar2","op":"attr","set":{"fill":"#0072B2"}},{"id":"grp","op":"remove|insert_after|insert_before|replace","svg":"<g .../>"}]}` and `python3 $S/figkit.py edit FILE.svg /app/work/ops.json --reason "..."`. Put extra `content_map`, `exceptions` or `allowed_ids` in `/app/work/edit_meta.json` before running. Elements outside the ops stay byte-identical.

## If something goes wrong

- `SPEC ERRORS` / `CANNOT DRAW`: nothing was overwritten; fix the named entry.
- `layout_collisions`: shorten labels, set `"direction":"LR"`, `"TB"` or `"WRAP"` (long numbered routes), move detail to `note`/caption, or split the panel.
- too tall: use LR, or cut nodes no must-show item needs.
- `numbers_traceable`: cite the passage that has the number, or correct it; if it is computed, say so in the label and in `decisions` with the formula.
- unreadable PDF/image or missing data: record it in `unresolved` with what you tried; never fill the gap from memory.
- No exporter works: SVG and result.json stay valid, status is partial; do not write your own exporter. Font problems appear as `fonts_not_embedded` in `pdf_export`; keep live text.

`result.json` is written by the engine with the contract fields; do not rewrite it. If a case contract has extra root fields, add them with a few lines of Python that load, set and save the file after the last build.

For people: `references/guide.md` (method, limits, a four-panel example) and `examples/synthetic` (`figkit.py selftest`).
