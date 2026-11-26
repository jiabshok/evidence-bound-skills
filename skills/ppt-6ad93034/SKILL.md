---
name: slide-generate-edit
description: Generate academic slides or edit an existing deck by instruction - rewrite for an audience, update numbers, tables and native charts, add, split, reorder or delete slides - keeping untouched slides identical, with operation log, per-slide diff, PDF and result.json. Use for any slide generation or editing task whose input is in /input with a slide-workorder, and usually starting-deck.pptx.
---

# Academic slide generation and editing

Mode from the work order: starting deck plus instructions -> `edit`; no starting deck -> `build`; starting deck that must move to another template -> `adapt`, then continue with edits. Not for writing papers, statistics or drawing figures.

**Never inspect `/app/output` with your own commands** (cat, sed, ls, python on result.json, edit_record.json, REPORT.md): every engine command prints what it found, `review` prints the claims, `verify` prints the final state. Each extra read costs 30-60 s of a 15-minute run.

## Rules for this task

- Turn every instruction into ops and tick them off; give each op `edit` (the instruction's id), `src` and `reason`. Read affected slides first: `slide N --start`.
- Narrow scope: do not restyle, reword or correct anything not requested. A protected slide is never touched, even when it is wrong or a check complains about it: write it to `unresolved`.
- A changed number changes everywhere it describes the same quantity on slides you may edit: title, text, table, chart, notes, source line. Look for the old value on all slides; one left on a protected slide is an `unresolved` conflict with both values.
- Splitting: `set_text` the original with the first half, `add_slide` after it with the second half, divide the notes; every item exactly once.
- New slides use the deck's own layouts and the content rules below (claim title, sourced bullets, notes). Content rules 2, 7 and the last half of 4 apply only to slides you add.
- After `edit`, `change_record.json` -> preservation -> `slides_xml_identical` must list every slide you did not mean to touch.

## How this works

You write ONE small file (`/app/work/deck.json`, or `/app/work/edits.json` when editing). The bundled engine does layouts, native charts/tables/diagrams, notes, footers, citations, PDF export, checks on the saved deck and a complete `/app/output/result.json`. Do not write your own export or JSON code (only exceptions: the font snippet below, extra root fields) and do not read the engine source or the example files: everything you need is on this page.

`S=/skills/weekly-skill/scripts` (use the directory this SKILL.md is in if it differs).

| step | command | budget |
|---|---|---|
| 1 | `python3 $S/deckkit.py brief` - case, work order, layouts, starting deck with shape ids, passage ids; saves a first honest result.json | 1 call |
| 2 | `python3 $S/deckkit.py audit` (conflicts, n, limits, hedges), then `show P004-P012` / `find WORD` / `table FILE` / `slide N` - read what the slides need | 2-6 calls |
| 3 | write the spec file | 1-3 calls |
| 4 | `build`, `adapt` or `edit` (see mode) - fix each failed op and each ATTENTION / SLIDE / SOURCE line about slides you made or changed, rerun | 1-4 calls |
| + | **`python3 $S/deckkit.py review`** after the content is complete - prints every claim next to the sentence it cites and the whole requirement list: correct wrong direction, sign, strength, condition, unit or citation; add every missing required item (use `show`/`table` to fetch it). It ends with POSSIBLY MISSING lines: close every real gap, rebuild, review again. Accuracy and completeness weigh far more than speed; watch the printed minutes: requested edit done by minute 8, verify by minute 10 (cut at 15; the model may be slow) | 2-5 |
| 5 | `read_image /app/output/contact_sheet.png` once; fix what a viewer would notice | 1-2 calls |
| 6 | `python3 $S/deckkit.py verify`, then stop | 1 call |

**Hard limit: one response (thinking + text + tool call) over 16384 tokens aborts the whole run.** Think briefly, decide once, and write early. Write `/app/work/deck.json` with the top-level keys and the first 3-4 slides, then (build only) `/app/work/slides_2.json`, `slides_3.json` ... (each a JSON list of the next 3-4 slides; build appends them in order). `edits.json` is one file: about 12 ops per write, append the rest in a second call. Do not print whole files or draft in thinking and then write again.

Have a first build/edit before call 14 or minute 6; after it the deliverables are complete. Stop only after a second review shows no real gap; then do not polish appearance further.

## Decide the content before writing the spec

1. From the work order: mode, exact slide count, minutes, audience, language, template, preservation and uncertainty rules. These override everything here.
2. Storyline: problem -> gap -> approach -> 2-4 key results -> limits -> message. One claim per slide; the title IS the claim as a full short sentence (max about 12 words); explanation and caveats go to notes.
3. Strength: write "was associated with", "in this model", "proposed" exactly as strongly as the source. Not significant is not "no effect"; not reported stays "not reported"; simulations are not measurements; other people's results are named as such.
4. Before finishing, go through the `audit` leads once: every real conflict or gap that touches the talk (text vs table, n, dates, units, missing facts) becomes one `unresolved` entry with both values and passages, and the important ones appear on the limits slide.
5. Numbers: copy as printed, with unit, n and interval. If text and table disagree, use the table value and record both in `unresolved` and in the notes.
   - "Replace all values from FILE" means every column and row of that file (`set_table` with all columns; shorten headers, or a second small table), chart, title, notes and source line together; compare with `table FILE` afterwards.
   - A limitations slide: run `find limit`, `find unknown`, `find "not "` and `audit`; merge into the allowed number of points so that each limit the source names is covered (what could not be tested, unknown or censored data, sample/community scope, correlation only, instrument limits).
   - `unresolved` also lists each protected slide that the edit leaves inconsistent (slide number, both values) and each inconsistency inside the source (percent vs count, date ranges, n).
   - A ratio or "x-fold" headline compares like with like (same model, target, condition) and both numbers are on that slide. An optimum, dose or prediction outside the tested range says so on that slide. Fixed prices, constant weather, how data were split (same trial in train and test?) and similar assumptions stand next to the number they carry.
   - Never claim a ranking, trend or mechanism for which no metric or test is reported. Two values for one quantity (abstract vs table, text vs figure): name both on the slide that shows it.
   - A dense multi-panel source figure is unreadable when projected: use only the panel needed, or a native chart/table from the supplied numbers.
6. Every slide and every factual bullet has `src`: passage ids (`"P012"`, `["P012","P015"]`), a data file (`"file.csv"`, `"file.csv#3-9"`) or `"workorder"`. `build` searches every printed number in its cited source; `edit` prints LEAD for numbers found nowhere in the material.
7. At least half of the content slides carry a native visual: chart from a data file, table, flow, stats, or a supplied image. Never redraw data you do not have.

## deck.json

```json
{"title":"Talk title","audience":"who, what they know","goal":"what they should remember","storyline":"a -> b -> c","footer":"short footer",
 "slides":[
  {"kind":"title","title":"...","subtitle":"authors, source paper, occasion","notes":"...","minutes":0.5,"src":"P001"},
  {"kind":"content","role":"problem","title":"Claim sentence","bullets":[{"text":"short phrase","src":"P004"},{"text":"detail","level":1,"src":"P004"}],
   "takeaway":"one-line message","notes":"spoken script, 50-110 words: transition, pointer, caveat","minutes":1.5,"evidence":"measured|model|association|author interpretation","src":["P004"]},
  {"kind":"content","role":"result","title":"...","bullets":[...],"chart":{"type":"bar|barh|line|scatter|stacked|pie","data":"values.csv","x":"dose","y":"mean","group":"arm","where":{"day":["7"]},"xlabel":"Dose (mg)","ylabel":"Signal (a.u.)","note":"Mean, n = 5; SD in backup"},"notes":"...","src":["values.csv","P009"]},
  {"kind":"content","role":"method","title":"...","flow":["step one","step two"],"notes":"...","src":["P006"]},
  {"kind":"content","role":"data","title":"...","table":{"header":["A","B"],"rows":[["1.2","3.4"]],"src":"P011","caption":"Table 2","highlight":[0]},"notes":"..."},
  {"kind":"content","role":"result","title":"...","stats":[{"value":"12 ms","label":"median delay","src":"P012"}],"bullets":[...],"notes":"..."},
  {"kind":"two","title":"...","left":{"heading":"What was shown","bullets":[...]},"right":{"heading":"What was not shown","bullets":[...]},"notes":"...","src":["P013"]},
  {"kind":"section","title":"..."}],
 "qa":[{"q":"likely hard question","a":"answer with its limit","src":"P015","slide":6}],
 "unresolved":[{"item":"...","state":"conflict|not reported|ambiguous","detail":"both values","src":["P008","P021"]}],
 "omitted":[{"item":"...","reason":"..."}],"decisions":["why this selection/order/layout"]}
```

- `kind` picks a template layout by its real placeholders (title, content, two, compare, section, picture, titleonly); `"layout":"exact name"` overrides. `image`: {"path":"file from input","caption":"Fig. 2 ...","src":"P010"}. Tables may use `"data":"file.csv","columns":[...],"where":{...}`.
- Limits: title <= 2 lines, <= 5 bullets of <= 14 words beside a visual or <= 6 without, table <= 7 columns x 9 rows, <= 5 flow steps. Text that cannot fit is reported: cut words, do not shrink.
- Markup: `*italic*`, `**bold**`, `_{sub}`, `^{sup}`. Notes never repeat the bullets.
- The slide count in the spec must equal the work order exactly (title, backup and Q&A slides count unless the work order says otherwise). Per-slide `minutes` must add up to the requested time (backup slides 0).

## edits.json (starting deck stays the base; untouched slides stay identical)

Synthetic example: revised table, chart, text, notes (E1), a split (E2), a new slide (E3), protected slide 1 now inconsistent.

```json
{"footer":"same footer text as the other slides","ops":[
 {"op":"set_cell","slide":4,"shape":"#7","row":8,"col":2,"text":"26.1","edit":"E1","src":"rev.csv#8","reason":"revised value"},
 {"op":"update_chart","slide":3,"shape":"#9","chart":{"categories":["0","60"],"series":{"vehicle":[10.2,88.1],"INH-7":[9.9,26.1]}},"edit":"E1","src":"rev.csv"},
 {"op":"replace_text","slide":3,"old":"24.3","new":"26.1","edit":"E1","src":"rev.csv#8"},
 {"op":"set_notes","slide":4,"text":"full new notes","before":"old notes","edit":"E1","src":"rev.csv"},
 {"op":"set_notes","slide":5,"text":"first half","edit":"E2"},{"op":"set_text","slide":5,"shape":"#3","items":["first item",{"text":"detail","level":1}],"edit":"E2","src":"P003"},
 {"op":"add_slide","id":"second","after":5,"spec":{"kind":"content","layout":"Title and Content","title":"...","bullets":[{"text":"moved item","src":"P002"}],"notes":"second half","src":["P002"]},"edit":"E2","src":"workorder"},
 {"op":"add_slide","id":"limits","after":"second","spec":{"kind":"content","title":"...","bullets":["..."],"notes":"...","src":["P004"]},"edit":"E3","src":"workorder"}],
 "unresolved":[{"item":"slide 1 (protected) still says 24.3","state":"conflict","detail":"slide 1: 24.3; rev.csv row 8: 26.1; left unchanged as instructed","src":["rev.csv#8"]}],
 "decisions":["E2: split at ...","time plan: s1 0.5, s2 1.5 ... = 13 min"],"omitted":[]}
```

| op | meaning (shape = `"#id"`, exact name, or `"title"`; top-level shapes only) |
|---|---|
| `set_title` `text` / `set_text` `shape`,`items` | replace the title / all paragraphs in the first run's or first paragraph's format; markup dropped; a plain string gets level 0, so give `level` |
| `set_text` `shape`,`paragraph`,`text` | one paragraph; 0-based = `pN` in `slide N` |
| `replace_text` `slide`,`old`,`new` | every match within a paragraph, incl. table cells and groups; substring, so give context ("74.5%", not "7"). Not notes or charts. Always give `slide`, else protected slides change too. Optional `shape` (not a table) |
| `set_cell` `row`,`col`,`text` | 0-based, row 0 = header, same as `rRcC` in `slide N`; old value logged |
| `set_table` `rows` | header + all rows; same size keeps the format, another size rebuilds the table |
| `update_chart` `chart` | new data, same native chart; old data logged. Give ALL series and categories; not for scatter. Inline `categories`/`series` keep the existing labels; `{"data","x","y","group","where"}` takes labels from the file |
| `set_notes`, `append_notes` `text` | whole notes / added line |
| `add_slide` `spec`,`after` | one deck.json slide; `after` = original number, an earlier `id`, or 0 = first; `id` a word, usable later as `slide`. No `after` = at the end |
| `delete_slide`; `move_slide` `to` | `to` = 1-based position at that moment; put moves last |
| `delete_shape`; `move_shape` `left`,`top`,`width`,`height` (inches); `replace_image` `path`,`alt` | pass the old `alt` text again |

Ops run in order. In ops, slide numbers always mean the ORIGINAL numbering, whatever was added, moved or deleted; `slide N` shows the current output by its FINAL number (`--start` = original). `edit` starts again from the starting deck, so keep all ops in one file and rerun; removing an op rolls it back. Text ops do not log the old text: add `"before"`. The engine makes no time plan in edit mode: put it in `decisions`.

`"continue":true` (only after `adapt`): base and numbering = the current output; a rerun stacks on the last one, so rerun `adapt` first. Copy adapt's `change_record.json` aside: `edit` rewrites it.

No op changes fonts, size, colour, layout or transitions. Only if told to remove a local font: run this before `edit`, add `"base":"base.pptx"` to edits.json and say so in `decisions` (checks then compare with this base):

```python
from pptx import Presentation
p=Presentation('/input/artifacts/starting-deck.pptx')
for n,ids in {6:[2]}.items(): # slide: shape ids (also text you split)
  for sh in p.slides[n-1].shapes:
    if sh.shape_id in ids:
      for q in sh.text_frame.paragraphs:
        for r in q.runs: r.font.name=None
p.save('/app/work/base.pptx')
```

## If something goes wrong

- `SPEC ERRORS` / `CANNOT BUILD`: nothing was overwritten; fix the named entry.
- `failed: ...` op: the message names the cause (existing shapes or columns). Fix or drop the op and rerun, else status stays partial. An instruction that cannot be done (shape or source missing, unsupported) goes to `unresolved`; leave that slide alone.
- "does not fit": shorten, split, or move detail to notes.
- `numbers_traceable` / LEAD on your text: cite the passage with the number or correct it; if computed, say "computed from ..." and give the formula in notes and `decisions`.
- missing placeholder: the closest layout is used and reported; never edit the master.
- fonts missing in the renderer: disclosed automatically.
- unreadable input, encrypted PDF, missing figure: `unresolved` with what you tried; never fill from memory.

`result.json` is written by the engine with the contract fields; do not rewrite it. Extra root fields in a case contract: load, set and save the file after the last run.

For maintainers: `references/guide.md` (method, limits, reproducible edit example) and `examples/synthetic` (`python3 $S/deckkit.py selftest`). Same-input comparison with and without this Skill on local practice cases: `references/evidence.md` (not needed during a run).
