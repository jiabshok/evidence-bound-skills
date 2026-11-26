---
name: scientific-data-chart
description: Generate or edit scientific data charts (bar, stacked, line, scatter, dot, box, heatmap, forest, multi-panel) from supplied tables, with per-mark row provenance, geometry read-back against the source table, editable SVG, PNG/PDF and result.json. Use for any data chart task whose input is in /input with a figure-workorder and data files.
---

# Scientific data chart: generate, edit and prove it

Use when the task is to draw or edit charts from source data. The value of the figure is that each mark equals a table cell; the engine proves this by inverting the drawn geometry back to numbers.

## Rules for this task

- Run `table FILE` first: note units, grouping columns, missing values, replicates versus summaries, and what the error column means. If the meaning of the error column is not stated anywhere, plot it only if asked, set `err_meaning` to "not stated in source" and add an `unresolved` entry.
- Choose the chart by the question: change over ordered x -> line; compare categories -> bar (from zero) or dot; raw observations or distribution -> box (draws every point) or scatter; estimates with intervals -> forest; matrix -> heatmap; magnitudes over decades -> `"yscale":"log"`. Never average, normalise, drop or impute rows unless the work order says so. Aggregate only through `derive`, `reduce` and `stat`, so that every value keeps its source rows; state formula and n in `note` and caption. Individual observations stay visible unless the work order says otherwise.
- Every series needs a distinguishable marker, dash or hatch (automatic) and a legend label; set `labels` to expand codes and `order`/`group_order` to keep the scientific order. Axis labels: quantity (unit). Say n and the error definition in `note` and caption.
- Use significance marks only when the source gives test and p value; write test and p in `note` with their `src`. An on-plot mark is an overlay `{"type":"text","data":"marks.csv","x":"arm","y":"y","label_col":"mark","layer":"B-sig","src":"P009"}` with `/app/work/marks.csv` holding columns arm (raw code), y (height inside the axis), mark. Do not draw trend lines that were not fitted in the source.
- Traps the engine does not flag: `stat` works only for line, bar, dot and forest (ignored for scatter, box, stacked, heatmap); `stat_by` only for `line` with numeric x; `value_labels` prints the drawn value (4 significant digits with `stat`/`derive`); `where` compares raw cell strings exactly as `table` prints them; `reduce` keeps the other columns of the first row, so `by` must contain x and group. Use `stat` only on raw replicates, never on a table that already holds means (there use `err` or `lo`+`hi`).
- `NOTE ... rows hold no numeric value and are not drawn`: those rows are not in result.json by themselves; add one `unresolved` entry with file, row numbers (with `derive` they count filtered rows) and raw content, and give the remaining n. Before plotting look in the `table` summary for a min/max off by orders of magnitude, mixed units or duplicated rows; plot as supplied and record it, never repair silently.
- Several questions -> several panels with the same y unit aligned in one row; do not use dual axes.
- For an edit, change only the requested property, rebuild with `--revise`, and confirm in `decisions` that data, scales and the other panels are unchanged.

## How this works

You write small text files in `/app/work`. The bundled engine does everything mechanical: layout, orthogonal routing, vector drawing, SVG/PNG/PDF export, reading the delivered files back, resolving every citation, and writing a complete `/app/output/result.json`. Do not write your own SVG, matplotlib, export or JSON code, and do not read the engine source or example files: everything you need is on this page.

`S=/skills/weekly-skill/scripts` (use the directory this SKILL.md is in if it differs).

**Budget: 64 requests, 900 s; aim for about 15 calls. Hard limit: one response (thinking + text + tool call) over 16384 tokens aborts the whole run with nothing further saved.** This is the most common failure. Never think the whole figure through at once: write at most 2 chart panels (or 6 nodes / 6 relations) per response, build, go on. Corrections are cheap; a dead run is not.

| step | command | calls |
|---|---|---|
| 1 | `python3 $S/figkit.py brief` - case, work order, files, tables, passage ids; saves a first honest result.json | 1 |
| 2 | `python3 $S/figkit.py audit` (conflicts, n, percentages, limits, hedged statements), then `show P004-P012` / `find WORD` / `table FILE` (first 40 rows + summary; `table FILE 41-80` for more) | 2-4 |
| 3 | write `/app/work/spec.json` with title, canvas, caption and the first two panels; add further panels in later responses | 1 |
| 4 | `python3 $S/figkit.py build`; fix ATTENTION lines, rebuild | 1-4 |
| + | **`python3 $S/figkit.py review`** after the content is complete - prints every claim next to the sentence it cites and the whole requirement list: correct wrong direction, sign, strength, condition, unit or citation; add every missing required item (use `show`/`table` to fetch it). It ends with POSSIBLY MISSING lines: close every real gap, rebuild, review again. Accuracy and completeness weigh far more than speed; watch the printed minutes: requested edit done by minute 6, verify by minute 8 (cut at 15; the model may be slow) | 2-5 |
| 5 | `read_image /app/output/figure.png` once; correct what a reader would misread | 1-2 |
| 6 | requested edit: change the files/spec, then `python3 $S/figkit.py build --revise "what and why"`; for a supplied SVG use `svgtree` + `edit` | 1-3 |
| 7 | `python3 $S/figkit.py verify`, then stop | 1 |

Follow the NEXT line each command prints. Have the first build before minute 4. After any build the deliverables are complete, so an interruption never leaves an empty output. Stop only after a review shows no real gap; do not polish appearance further and do not inspect files with your own scripts.

## Decide the science before drawing

1. From the work order note: must-show items, forbidden claims, required sizes/formats, language, the edit request.
2. Diagram panels only: for each candidate arrow ask: does a passage state this relation, with this direction, under this condition? Stated or observed -> `"certainty":"stated"`. Proposed, hypothesised, "may", "suggests", model-only -> `"certainty":"proposed"` (drawn dashed, legend added automatically). Correlation -> type `association` (no arrowhead). Not supported -> leave it out and list it in `omitted` or `unresolved`.
3. Numbers: copy exactly as printed, with unit, n and meaning of the +/-. If text and table disagree, show neither silently: use the table value, and record both in `unresolved`.
4. Before finishing, go through the `audit` leads once: every real conflict or gap that touches the product (text vs table, n per analysis, dates, signs, units, interactions, corrections, missing design facts) becomes one `unresolved` entry with both values and passages. Absence of evidence is not evidence of absence: "not significant" never becomes "no effect" or "equal". "Not reported" stays "not reported".
5. Every node, edge, chart and text item needs `src`: passage ids (`"P012"`, `["P012","P015"]`), a data file (`"file.csv"` or `"file.csv#3-9"`), or `"workorder"`. Cite the passage that states that exact fact. The engine searches every printed number in the cited source and reports those it cannot find.

## spec.json

Example (invented data: `wells.csv` has columns day, arm, well, signal, od; one row per well). A = replicates over time, B = computed ratio at one time point:

```json
{"title":"One-sentence claim the evidence supports","title_src":"P001",
 "canvas":{"width_mm":180,"font_pt":8,"dpi":300,"formats":[]},
 "layout":[["A","B"]],
 "panels":[
  {"id":"A","type":"chart","chart":"line","title":"Time course","data":"wells.csv","x":"day","y":"signal","group":"arm",
   "group_order":["veh","drug"],"labels":{"veh":"Vehicle","drug":"Drug"},"stat":"mean_sd","err_meaning":"SD, n = 3 wells",
   "xlabel":"Time (day)","ylabel":"Signal (a.u.)","note":"Mean ± SD and every well, n = 3","src":["wells.csv","P001"],"weight":1.4},
  {"id":"B","type":"chart","chart":"bar","title":"Day 7 per OD","data":"wells.csv","where":{"day":["7"]},
   "derive":{"ratio":"[signal] / [od]"},"x":"arm","y":"ratio","group":"arm","order":["veh","drug"],
   "labels":{"veh":"Vehicle","drug":"Drug"},"stat":"mean_sd","err_meaning":"SD, n = 3 wells",
   "xlabel":"Arm","ylabel":"Signal / OD (a.u.)","note":"Ratio = signal / od per well","src":["wells.csv","P001"]}],
 "caption":"Self-contained: panels, abbreviations, n, error definition, formula of each computed value.",
 "footnotes":[{"text":"...","src":"workorder"}],
 "unresolved":[{"item":"well d, day 7","state":"missing","detail":"row 19: signal empty, not drawn","src":["wells.csv#19"]}],
 "omitted":[{"item":"...","reason":"..."}],
 "decisions":["why this encoding/layout"]}
```

Table that already holds summaries: no `stat`; `"y":"mean","err":"sd","err_meaning":"SD, n = 5"`. Text panel: `{"id":"C","type":"text","title":"...","items":[{"value":"2.8 nm","text":"mean pore size","src":"P010"}]}`. Diagram panel, only if the work order asks for one: `{"id":"D","type":"diagram","direction":"LR","nodes":[{"id":"K","label":"Kinase K","kind":"enzyme","src":"P004"},{"id":"g","label":"*g*","kind":"gene","src":"P005"}],"edges":[{"from":"K","to":"g","type":"activation","certainty":"stated","src":"P005"}]}`; kinds: protein receptor enzyme complex gene mrna small_molecule drug cell organism phenotype process step sample data model result; types: activation inhibition binding phosphorylation transport expression conversion flow association.

- `canvas`: exact page `"size_mm":[180,100]` (or `"size_px":[1600,1000]`) and smallest allowed text `"min_font_pt":7` when the work order gives them; extra export formats in `formats` (tiff, jpg, eps).

- chart types: bar stacked line scatter dot box (raw observations) heatmap (`x`,`y`,`value`) forest (`x`=label,`y`=estimate,`lo`,`hi`,`ref`). Set `group` equal to `x` to colour bars by category (same colours as that group in other panels). Data may be CSV, TSV, JSON records or `"book.xlsx!Sheet name"` (`@2` for its second table block). Keys: `where`, `group`, `order`, `group_order`, `labels` {raw: shown}, `err` or `lo`+`hi`, `err_meaning`, `yscale`/`xscale` "log", `ylim`, `value_labels`, `annotations` [{"y":0.05,"text":"threshold"}] (horizontal line), `xlim`, `colors` {raw group: "#hex"}, `legend` false, `height_mm`.
- chart computations (never compute by hand): `"derive":{"ratio":"[Lum] / [OD600]"}` adds a column per row (+ - * / ** log10 log2 ln sqrt); `"reduce":{"by":["strain","culture"],"y":"ratio","fn":"max"}` (max min mean median sum count first last); `"stat":"mean_sd|mean_sem|mean_ci95|median_iqr|geomean_sd"` draws the summary of replicates (same x and group) plus every individual point. All drawn values, n and contributing rows go to `plotted_values.csv`. To plot y against a measured x per cell, add `"stat_by":["time"]`: cells are stat_by + group, x and y are both summarised and horizontal bars are drawn. Values that exist only as printed text: `"inline":{"columns":["site","mean","se"],"rows":[["A","1.2","0.3"]]}` instead of `data`, with `src` of the passages that print them. Horizontal errors: `xerr` or `xlo`+`xhi`.
- shared-axis `overlays` in a chart panel: [{"type":"line|points|ring","data":"other.csv","where":{...},"x":"..","y":"..","layer":"name","label":"..","dash":"dashed","color":"#444","label_col":"name"}, {"type":"abline","slope":0.73,"intercept":1.2,"space":"log10","label":"..."}, {"type":"hline","value":1,"label":".."}, {"type":"vline","value":3}]. `ring` without `data` circles rows of the main table chosen by `where`.
- text markup everywhere: `*italic*`, `_{sub}`, `^{sup}`. Gene symbols italic, proteins upright, as in the source.
- Keep labels short (about 1-5 words); conditions go on the edge label or `note`; explanation goes to the caption. `panels` in one row share width by `weight`; a nested list is a column, e.g. `[["A",["B","C"]]]` puts B above C to the right of A.

## Editing so that everything else is preserved

- Figure you built (always use this route for it, never `edit`): edit only the affected spec entries, add `"edit_scope":["id fragment", ...]` (what may change: a panel id `"A"` = everything in A, or id parts `"A-legend"`, `"A-line-1"`, `"A-raw-r4"`, `"A-bar-r3"`, `"A-axes"`, `"B-sig"`) and/or `"edit_protect":["B"]` (what must not change; write the bare panel id, `"B-"` matches nothing), then `build --revise "..."`. The first version is frozen as `figure_before_edit.*`; every later `--revise` is compared with it (a plain `build` starts a new v1). Removing an edge = delete it from the spec; adding text (an inset, a list, a note) = add a `text` panel at the end or a footnote, which is placed below so nothing above moves. Unaffected entities and connectors keep their geometry; before/after files, changed/added/removed ids, count of byte-identical elements and rollback are written to `edit_record.json`.
- Example, "recolour Drug in A, leave B": in spec.json add `"colors":{"drug":"#D55E00"}` to panel A and at top level `"edit_scope":["A"],"edit_protect":["B"]`, then `build --revise "Drug series in A recoloured to #D55E00 as requested"`. Changed ids are then A-legend, A-line-1 and the Drug points; axes and B stay byte-identical. New axis range or log scale: same route, but every mark of A moves, so say so in `decisions`. Do all requested changes in one `--revise`.
- SVG supplied by the case: `svgtree FILE.svg`, then `/app/work/ops.json` = `{"ops":[{"id":"label_3","op":"text","old":"5 mM","value":"5 uM","reason":"...","src":"P007"},{"id":"bar2","op":"attr","set":{"fill":"#0072B2"}},{"id":"grp","op":"remove|insert_after|insert_before|replace","svg":"<g .../>"}]}` and `python3 $S/figkit.py edit FILE.svg /app/work/ops.json --reason "..."`. Put extra `content_map`, `exceptions` or `allowed_ids` in `/app/work/edit_meta.json` before running. Elements outside the ops stay byte-identical.

## If something goes wrong

- `SPEC ERRORS` / `CANNOT DRAW`: nothing was overwritten; fix the named entry.
- `layout_collisions`: shorten labels, (diagram) set `"direction":"LR"` or `"TB"`, move detail to `note`/caption, or split the panel.
- too tall or long category labels: put panels side by side in `layout`, shorten with `labels` (full name in caption), raise `height_mm`.
- log axis with zero or negative values: use a linear axis, or keep log and exclude them by `where` with an `unresolved` entry naming the rows; no bars on a log axis.
- `numbers_traceable`: cite the passage that has the number, or correct it; if it is computed, say so in the label and in `decisions` with the formula.
- unreadable PDF/image or missing data: record it in `unresolved` with what you tried; never fill the gap from memory.
- No exporter works: the SVG and result.json are still valid; status becomes partial and says so.

`result.json` is written by the engine with the contract fields; do not rewrite it. If a case contract has extra root fields, add them with a few lines of Python that load, set and save the file after the last build.

See `references/guide.md` for usage, method, limits and maintenance, and `examples/synthetic` for a complete input, spec and expected shape of the output (`python3 $S/figkit.py selftest`). Same-input comparison with and without this Skill on local practice cases: `references/evidence.md` (not needed during a run).
