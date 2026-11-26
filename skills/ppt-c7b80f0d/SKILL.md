---
name: paper-to-slides
description: Turn a supplied paper or research material into an editable academic PPTX in the supplied template, with claim-style pages, native charts and tables, speaker notes, page-level evidence map, PDF export, checks and result.json. Use for any paper-to-slides task whose input is in /input with a slide-workorder and target-template.pptx.
---

# Paper to academic slides

Structural rewrite: the paper's contribution becomes a sequence of one-claim pages, each tied to a figure, table, section or data row. Mode: `build`. Only if the work order asks to change a supplied starting deck use `edit`; to move a starting deck into the template use `adapt` (no spec file).

## Rules for this task

- Before planning read abstract, last introduction paragraph, core methods, the results you will cite, captions/tables and limitations. Write the contribution in one sentence; every slide must serve it.
- Required pages (merge or split to hit the exact count): title; problem and gap; what was done (flow); data/design with n; 2-4 key results, each with its figure/table/number; limits and what is not shown; take-home message.
- Keep figure/table numbers correct: cite the figure next to the claim it supports and only if the caption says so. Distinguish main result, supporting detail and other people's results.
- Result values: prefer a native table or chart. No data file? Type the paper's table values into an inline `table` or `chart` (below) with `src` = that passage. Label schematic or simulated figures as such.
- Figure image: supplied file, else crop it from a supplied paper PDF (one or two calls): `pdftoppm -png -r 200 -f PAGE -l PAGE -x X -y Y -W W -H H FILE.pdf /app/work/fig2`, then use the file name `ls` shows as `image.path`, caption "Fig. 2 (p. 5)". Not extractable: record in `unresolved`, show the numbers the text gives. Never redraw curves by eye.
- Formula: type it only if the passage text is legible; if it is an image, crop it like a figure or cite "Eq. N, p. X" and record it.

## How this works

You write ONE small file (`/app/work/deck.json`, or `/app/work/edits.json` when editing). The bundled engine fills the supplied template's real layouts and placeholders, fits text, makes native charts/tables/diagrams, adds notes, footers and citations, exports the PDF, re-reads the saved deck, looks up every cited id and writes a complete `/app/output/result.json`. Do not write your own python-pptx, export or JSON code, and do not read the engine source or example files: everything you need is on this page.

`S=/skills/weekly-skill/scripts` (or `scripts` beside this file); set it again in each shell call.

| step | command | budget |
|---|---|---|
| 1 | `python3 $S/deckkit.py brief` - case, work order, template layouts, starting deck, tables, passage ids; saves a first honest result.json | 1 call |
| 2 | `python3 $S/deckkit.py audit` (conflicts, n, percentages, limits, hedged statements), then `show P004-P012` / `find WORD` / `table FILE` / `slide N` - read what the slides need | 2-6 calls |
| 3 | write the spec file | 1-3 calls |
| 4 | `python3 $S/deckkit.py build` (or `edit`, `adapt`) - fix each ATTENTION / SLIDE / SOURCE line, rerun | 1-4 calls |
| + | **`python3 $S/deckkit.py review`** after the content is complete - prints every claim next to the sentence it cites and the whole requirement list: correct wrong direction, sign, strength, condition, unit or citation; add every missing required item (use `show`/`table` to fetch it). It ends with POSSIBLY MISSING lines: close every real gap, rebuild, review again. Accuracy and completeness weigh far more than speed; watch the printed minutes: requested edit done by minute 8, verify by minute 10 (cut at 15; the model may be slow) | 2-5 |
| 5 | `read_image /app/output/contact_sheet.png` once; fix what a viewer would notice | 1-2 calls |
| 6 | `python3 $S/deckkit.py verify`, then stop | 1 call |

**Hard limit: one response (thinking + text + tool call) over 16384 tokens aborts the whole run.** Think briefly, decide once, and write early. Write `/app/work/deck.json` with the top-level keys and the first 3-4 slides, then `/app/work/slides_2.json`, `slides_3.json` ... (each a JSON list of the next 3-4 slides; build appends every `slides_*.json` in name order, so stop at `slides_9` and keep each slide in one file only). Do not print whole files or draft in thinking first.

Have a first build before call 14 or minute 6. After a build the deliverables are already complete. Stop only after a second review shows no real gap; then do not polish appearance further.

## Decide the content before writing the spec

1. From the work order: mode, exact slide count, minutes, audience, language, rules about template, preservation and uncertainty. These override this page.
2. Storyline: problem -> gap -> approach -> 2-4 key results -> limits -> message. Follow the paper's contribution, not its section order. One claim per slide; the title IS the claim as a full short sentence (max about 12 words). Supporting detail goes to bullets; explanation, transitions and caveats go to notes.
3. Strength: write "was associated with", "in this model", "proposed" exactly as strongly as the source. Not significant is not "no effect". Not reported stays "not reported". Illustrations and simulations are never measurements; other people's results are named as such.
4. Before finishing, go through the `audit` leads once: every real conflict or gap that touches the talk (text vs table, n per analysis, dates, signs, units, interactions, corrections, missing design facts) becomes one `unresolved` entry with both values and passages, and the important ones appear on the limits slide.
5. Numbers: copy as printed, with unit, n and interval. If text and table disagree, use the table value and record both in `unresolved` and in the notes.
   - A ratio or "x-fold" headline compares like with like (same model, target, condition) and both numbers are on that slide. An optimum, dose or prediction outside the tested range says so on that slide. Fixed prices, constant weather, how data were split (same trial in train and test?) and similar assumptions stand next to the number they carry.
   - Never claim a ranking, trend or mechanism for which no metric or test is reported. Two values for one quantity (abstract vs table, text vs figure): name both on the slide that shows it.
   - A dense multi-panel source figure is unreadable when projected: use only the panel needed, or a native chart/table from the supplied numbers.
6. Every slide and factual bullet has `src`: passage ids (`"P012"`, `["P012","P015"]`), a data file (`"file.csv"`, `"file.csv#3-9"`, row numbers as `table` prints) or `"workorder"`. For a figure cite its caption passage. The engine searches the numbers in titles, bullets, takeaways, stats, typed tables and charts in the cited source and reports those it cannot find; check subtitles, flow steps, captions and notes yourself.
7. At least half of the content slides should carry a visual: chart, table, flow, stats, or a figure image.

## deck.json

```json
{"title":"Talk title","audience":"who, what they know","goal":"what they should decide or remember","storyline":"a -> b -> c","footer":"short footer",
 "slides":[
  {"kind":"title","title":"...","subtitle":"authors, source paper, occasion","notes":"...","minutes":0.5,"src":"P001"},
  {"kind":"content","role":"problem","title":"Claim sentence","bullets":[{"text":"short phrase","src":"P004"},{"text":"detail","level":1,"src":"P004"}],
   "takeaway":"one-line message","notes":"spoken script, 50-110 words: transition, what to point at, caveat, likely question","minutes":1.5,"evidence":"measured|model|association|author interpretation","src":["P004"]},
  {"kind":"content","role":"result","title":"...","bullets":[...],"chart":{"type":"bar|barh|line|scatter|stacked|pie","data":"values.csv","x":"dose","y":"mean","group":"arm","where":{"day":["7"]},"xlabel":"Dose (mg)","ylabel":"Signal (a.u.)","note":"Mean, n = 5; SD in backup"},"notes":"...","src":["values.csv","P009"]},
  {"kind":"content","role":"method","title":"...","flow":["step one","step two","step three"],"takeaway":"...","notes":"...","src":["P006"]},
  {"kind":"content","role":"data","title":"...","table":{"header":["A","B"],"rows":[["1.2","3.4"]],"src":"P011","caption":"Table 2, rows 1-4","highlight":[0]},"notes":"..."},
  {"kind":"content","role":"result","title":"...","stats":[{"value":"0.96 A","label":"median error, CASP14","src":"P012"}],"bullets":[...],"notes":"..."},
  {"kind":"two","title":"...","left":{"heading":"What was shown","bullets":[...]},"right":{"heading":"What was not shown","bullets":[...]},"notes":"...","src":["P013"]},
  {"kind":"content","role":"limits","title":"...","bullets":[...],"notes":"...","src":["P014"]},
  {"kind":"section","title":"..."}],
 "qa":[{"q":"likely hard question","a":"answer with its limit","src":"P015","slide":6}],
 "unresolved":[{"item":"...","state":"conflict|not reported|ambiguous","detail":"both values","src":["P008","P021"]}],
 "omitted":[{"item":"...","reason":"..."}],"decisions":["why this selection/order/layout"]}
```

- `kind` picks a template layout by its real placeholders (title, content, two, compare, section, picture, titleonly); `"layout":"exact name"` overrides. `image`: {"path":"file from input","caption":"Fig. 2 ...","src":"P010"}. Tables may use `"data":"file.csv","columns":[...],"where":{...}` (rows after 14 are cut: filter, name the rows in the caption).
- Inline chart: `"chart":{"type":"bar","categories":["A","B"],"series":[{"name":"Mean","values":[1.2,3.4]}],"ylabel":"Signal (a.u.)","src":"P011","note":"Table 2; n = 5"}` (bar, barh, line, stacked, pie; scatter needs `data`). Charts draw no error bars: say "means only" in `note` and give SD/CI in a table or bullet.
- One visual per slide (chart, table, image, flow or stats). `left`/`right` work only in `two`/`compare`, where a visual is dropped: for text plus visual use `content`.
- Limits that keep slides readable: title <= 2 lines, <= 5 bullets of <= 14 words beside a visual or <= 6 without, table <= 7 columns x 9 rows, <= 5 flow steps.
- Markup: `*italic*`, `**bold**`, `_{sub}`, `^{sup}`. Write notes for a speaker: never repeat the bullets.
- The slide count must equal the work order exactly (title, backup and Q&A slides count unless the work order says otherwise); for a maximum or a range, use the number `brief` prints, or if it prints None stay inside the limit. Per-slide `minutes` must add up to the requested time (backup slides 0).

## edits.json (starting deck stays the base; untouched slides stay identical)

```json
{"ops":[
 {"op":"replace_text","slide":3,"old":"12.4","new":"14.2","src":"values.csv#4","reason":"..."},
 {"op":"set_title","slide":2,"text":"..."},{"op":"set_text","slide":4,"shape":"#5","items":["a",{"text":"b","level":1}]},
 {"op":"set_cell","slide":5,"shape":"Table 1","row":2,"col":3,"text":"0.81"},{"op":"set_table","slide":5,"rows":[["h1","h2"],["1","2"]]},
 {"op":"update_chart","slide":6,"chart":{"data":"values.csv","x":"dose","y":"mean","group":"arm"}},
 {"op":"add_slide","id":"new1","after":6,"spec":{"kind":"content","title":"...","bullets":[...],"notes":"...","src":["P014"]}},
 {"op":"delete_slide","slide":8},{"op":"move_slide","slide":9,"to":4},{"op":"set_notes","slide":2,"text":"..."},{"op":"append_notes","slide":3,"text":"..."},
 {"op":"delete_shape","slide":4,"shape":"#7"},{"op":"move_shape","slide":4,"shape":"#7","left":1.0,"top":1.5,"width":5.0,"height":3.0},{"op":"replace_image","slide":4,"shape":"#8","path":"fig2.png"}],
 "unresolved":[],"decisions":[],"omitted":[]}
```

Ops run in the listed order. Slide numbers always mean the ORIGINAL numbering, whatever was added, moved or deleted before; `"after":"new1"` places a slide after one you added with that id; `to`/`position` is the final position at that moment, so put moves last. `replace_text`, `set_text`, `set_title` and `set_cell` keep the existing formatting (set_text copies the first paragraph's format). `edit` always starts again from the starting deck, so keep all ops in one file and rerun. Check with `slide N` (current output). Make only requested changes; a chart and the text that quotes it must change together; record anything inconsistent you were not asked to change in `unresolved`.

## If something goes wrong

- `SPEC ERRORS` / `CANNOT BUILD`: nothing was overwritten; fix the named entry. A `KeyError` means a chart or table lacks that key; same handling.
- `SOURCE` line (unknown id): correct the id; status stays `partial` while one is left, the slide count is wrong or the PDF is missing.
- Work order sets a minimum font: `grep -B3 -E '(title|body) [0-9]+->[0-9]+ pt' /app/output/result.json` lists shrunk text; below the minimum, cut words or split.
- page limit: merge supporting results; the rest goes to notes or `omitted`.
- "does not fit": shorten, split, or move detail to notes.
- `numbers_traceable`: cite the passage that has the number or correct it; if computed, say "computed from ..." on the slide and give the formula in notes and `decisions`.
- missing placeholder: the engine uses the closest layout and reports it; do not edit the master. No `# TEMPLATE` line in `brief`: `cp -r /input /app/work/in`, copy the .pptx there as `artifacts/target-template.pptx`, and put `KIT_INPUT=/app/work/in` before every command.
- missing fonts: the PPTX keeps them, PDF substitution is disclosed automatically.
- encrypted, scanned or damaged PDF (listed under FILES but no passage comes from it; `pdfinfo FILE` confirms): do not break the password; build from what is readable, put "source not readable" on the limits slide and in `unresolved`, never fill from memory. After the last build:
  `python3 -c "import json;p='/app/output/result.json';r=json.load(open(p));r['status']='partial';json.dump(r,open(p,'w'),ensure_ascii=False,indent=1)"`

## Deliverables (all written by `build` into /app/output)

| required group | files | result.json |
|---|---|---|
| editable deck | `presentation.pptx`, `deck_spec.json`, `speaker_plan.md` | `case_id`, `status`, `editable_source`, `time_plan` |
| page-level evidence map | `claim_source_map.csv` | `content_map`; uncertainty in `exceptions` |
| rendering and version record | `presentation.pdf`, `previews/`, `contact_sheet.png`, `change_record.json`, `rebuild/` | `export_artifact`, `compliance_checks`, `provenance` |

Do not rewrite `result.json` by hand. If a case contract has extra root fields, add them the same way (load, set, save) after the last build.

For people, not needed during a run: `references/guide.md` and `examples/synthetic` (invented input and spec; `selftest` builds its output). Same-input comparison with and without this Skill on local practice cases: `references/evidence.md` (not needed during a run).
