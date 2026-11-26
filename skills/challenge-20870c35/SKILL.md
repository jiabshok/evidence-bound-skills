---
name: presentation-storyline
description: Organise academic presentation content for a given goal, audience and time - narrative order, one key message per page, evidence strength, speaker notes, Q&A and backup pages - and deliver an editable PPTX in the supplied template with evidence map, PDF and result.json. Use for any presentation-structuring task whose input is in /input with a slide-workorder.
---

# Structuring an academic presentation

Use when the job is deciding what to say to whom in which order, and delivering it ready to present. Not for writing the paper, new analysis or drawing new data figures.

Mode: `build` in the supplied template. Use `edit` only if the work order wants the starting deck changed in place, `adapt` (no spec file) only if it must move as it is into another template. A starting deck that is only raw material: read it with `slide N --start`, then `build`.

**Never inspect `/app/output` with your own commands** (cat, sed, ls, python on result.json, edit_record.json, REPORT.md): every engine command prints what it found, `review` prints the claims, `verify` prints the final state. Each extra read costs 30-60 s of a 15-minute run.

## Rules for this task

- `goal`: a checkable outcome ("after the talk the audience can decide X / accept that Y holds under Z"). `audience`: who, what they know, what they care about, likely objections. `storyline`: the argument chain. All three are plain strings; use the work order's own goal and audience when given. They decide depth, jargon and cuts.
- Every selection goes into `decisions`, every cut of something a reader of the source would expect into `omitted` with the reason (3-6 each).
- Order by argument, not by paper section: decision needed -> gap -> idea -> strongest evidence -> robustness or counter-evidence -> limits -> consequence. Group meeting: method and progress first; defence: novelty and its boundary; review panel: conclusion and evidence strength first; non-specialists: the decision first, define each term once.
- Notes of EVERY slide (title and backup too) start with the transition from the previous page and end with the sentence that leads on.
- `evidence` on each content slide: measured, replicated, model, association, author interpretation, not reported (or the work order's own labels). It is saved in result.json only, so also say it on the slide, in `takeaway` or a bullet ("Model, test set: ..."), and word the title no stronger.
- `qa`: 5-8 hard questions (or the number asked): each audience objection, then mechanism, data/statistics, controls, generality, limits, next step. `a`: strength label plus 1-3 sentences, "not reported" when that is the answer. `slide`: the page to jump to. The engine does not check `qa` passage ids or numbers: copy them from text you read.
- Follow a main/backup split in the work order; otherwise make one backup slide if the count allows (role `backup`, minutes 0, real content a question needs).
- Time: 1-2 minutes per content slide, most for the strongest evidence. Sum within 15% of the requested time; if that time includes discussion, put it on the closing or Q&A slide.

Plan example (invented data, shows form only; these keys go into deck.json):

```json
{"goal":"group agrees which control to run before claiming INH-7 blocks ZK1",
 "audience":"cell-biology group; knows reporter assays, not this pathway; objections: off-target effect? only one time course?",
 "storyline":"claim at stake -> how ZK1 drives gla -> INH-7 lowers the signal (measured) -> feedback only proposed -> control to run",
 "decisions":["60-min result before the pathway detail: it is what the group must judge"],
 "omitted":[{"item":"10- and 30-min values","reason":"not needed for the decision; table on backup slide 6"}],
 "qa":[{"q":"Could INH-7 act elsewhere?","a":"Not reported: no binding-site data and no second inhibitor.","src":"P002","slide":5},
  {"q":"How variable is it?","a":"Measured: n = 4 wells, SD in the table; no significance test reported.","src":["P004","response.csv"],"slide":6}]}
```

## How this works

You write one small spec (`/app/work/deck.json`, or `/app/work/edits.json` when editing). The bundled engine fills the supplied template's real layouts and placeholders, fits text, makes native charts/tables/diagrams, adds notes, footers and on-slide citations, exports the PDF, re-reads the saved deck, resolves every citation and writes a complete `/app/output/result.json`. Do not write your own python-pptx, export or JSON-assembly code, and do not read the engine source or the example files: everything you need for `build` is on this page, and reading code has used up whole budgets.

`S=/skills/weekly-skill/scripts` (use the directory this SKILL.md is in if it differs).

| step | command | budget |
|---|---|---|
| 1 | `python3 $S/deckkit.py brief` - case, work order, template layouts, starting deck with shape ids, tables, passage ids; also saves a first honest result.json | 1 call |
| 2 | `python3 $S/deckkit.py audit` (conflicts, n, percentages, limits, hedged statements), then `show P004-P012` / `find WORD` / `table FILE` / `slide N` - read what the slides need | 2-6 calls |
| 3 | write the spec file | 1-3 calls |
| 4 | `build` (or `edit` / `adapt`, see Mode) - fix each ATTENTION / SLIDE / SOURCE line, rerun | 1-4 calls |
| + | **`python3 $S/deckkit.py review`** after the content is complete - prints every claim next to the sentence it cites and the whole requirement list: correct wrong direction, sign, strength, condition, unit or citation; add every missing required item (use `show`/`table` to fetch it). It ends with POSSIBLY MISSING lines: close every real gap, rebuild, review again. Accuracy and completeness weigh far more than speed; watch the printed minutes: requested edit done by minute 8, verify by minute 10 (cut at 15; the model may be slow) | 2-5 |
| 5 | `read_image /app/output/contact_sheet.png` once; fix what a viewer would notice | 1-2 calls |
| 6 | plan file (below) and `python3 $S/deckkit.py verify`, then stop | 1 call |

**Hard limit: one response (thinking + text + tool call) over 16384 tokens aborts the whole run.** Think briefly, decide once, and write early. Write `/app/work/deck.json` with the top-level keys and the first 3-4 slides (if `qa` is long, build first and add it afterwards), then `/app/work/slides_2.json`, `slides_3.json` ... (each a JSON list of the next 3-4 slides; build appends them in order). Do not re-derive the paper in your head, do not print whole files, do not draft in thinking and then write again.

Have a first build before call 14 or minute 6. After a build the deliverables are already complete, so an interruption never leaves an empty output. Stop only after a second review shows no real gap; then do not polish appearance further.

## Decide the content before writing the spec

1. From the work order: mode, exact slide count, minutes, audience, language, rules about template, preservation and uncertainty. These override everything here.
2. Storyline: problem -> gap -> approach -> 2-4 key results -> limits -> message. Follow the paper's contribution, not its section order. One claim per slide; the title IS the claim as a full short sentence (max about 12 words). Supporting detail goes to bullets; explanation, transitions and caveats go to notes.
3. Strength: write "was associated with", "in this model", "proposed" exactly as strongly as the source. Not significant is not "no effect". Not reported stays "not reported". Illustrations and simulations are never presented as measurements; other people's results are named as such.
4. Before finishing, go through the `audit` leads once: every real conflict or gap that touches the talk (text vs table, n per analysis, dates, signs, units, interactions, corrections, missing design facts) becomes one `unresolved` entry with both values and passages, and the important ones appear on the limits slide.
5. Numbers: copy as printed, with unit, n and interval. If text and table disagree, use the table value and record both in `unresolved` and in the notes.
   - A ratio or "x-fold" headline compares like with like (same model, target, condition) and both numbers are on that slide. An optimum, dose or prediction outside the tested range says so on that slide. Fixed prices, constant weather, how data were split (same trial in train and test?) and similar assumptions stand next to the number they carry.
   - Never claim a ranking, trend or mechanism for which no metric or test is reported. Two values for one quantity (abstract vs table, text vs figure): name both on the slide that shows it.
   - A dense multi-panel source figure is unreadable when projected: use only the panel needed, or a native chart/table from the supplied numbers.
6. Every slide and every factual bullet has `src`: passage ids (`"P012"`, `["P012","P015"]`), a data file (`"file.csv"`, `"file.csv#3-9"`) or `"workorder"`. The engine searches every printed number in the cited source and reports those it cannot find.
7. At least half of the content slides should carry a native visual: chart from a data file, table, flow, stats, or a supplied image. Use a figure image only if the file was supplied; never redraw data you do not have.

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

- `kind` picks a template layout by its real placeholders (title, content, two, compare, section, picture, titleonly); `"layout":"exact name"` overrides. `image`: {"path":"file from input","caption":"Fig. 2 ...","src":"P010"}. Tables may use `"data":"file.csv","columns":[...],"where":{...}`.
- Limits that keep slides readable: title <= 2 lines, <= 5 bullets of <= 14 words beside a visual or <= 6 without, table <= 7 columns x 9 rows, <= 5 flow steps. Text that cannot fit is reported: cut words, do not shrink.
- Markup: `*italic*`, `**bold**`, `_{sub}`, `^{sup}`. Write notes for a speaker: never repeat the bullets.
- The slide count in the spec must equal the work order exactly (title, backup and Q&A slides count unless the work order says otherwise). Per-slide `minutes` must add up to the requested time (backup slides 0).

## edit and adapt

Op list, numbering rules and adapt notes are in `references/edit_mode.md`; read it only if the work order needs one of these modes. `goal`, `audience`, `storyline`, `qa` then go to the top level of edits.json.

## If something goes wrong

- `SPEC ERRORS` / `CANNOT BUILD`: nothing was overwritten; fix the named entry.
- text/table/flow "does not fit": shorten, split, or move detail to notes.
- `numbers_traceable`: cite the passage that has the number or correct it; if computed, say "computed from ..." on the slide and give the formula in notes and `decisions`.
- template without a needed placeholder: the engine uses the closest layout and reports it; do not edit the master.
- fonts missing in the renderer: kept in the PPTX, substitution in the PDF is disclosed automatically.
- `SLIDE n: image only N dpi`: give the image the whole slide or state the key value in text; keep the original file, say so in notes. Formula or symbol missing in the extracted text: compare with the original page; if unclear, do not print it, record it in `unresolved`.
- template rule against work order (count, length, footer): the work order wins; record it in `decisions`.
- PDF not exported (`pdf_export`): rerun once, then leave status partial; the PPTX stays valid.
- `STOP RULE` printed, past minute 10 or call 50: no more polishing, run step 6.
- unreadable input, encrypted PDF, missing figure: record in `unresolved` with what you tried; never fill the gap from memory.

`result.json` is written by the engine with the contract fields; do not rewrite it. If a case contract has extra root fields, add them with a few lines of Python that load, set and save the file after the last build.

Plan file: notes, times and Q&A are already in `speaker_plan.md`; goal, storyline and cuts are in `result.json` (`narrative`, `design_decisions`, `omitted_from_source`). After the LAST `build` make the readable plan from the spec (the only extra code needed):

```
python3 - <<'E'
import json;o='/app/output/';d=json.load(open(o+'deck_spec.json'));L=['# Narrative plan']
L+=[f'{k}: {d.get(k,"-")}' for k in('goal','audience','storyline')]+['## Pages']
L+=[f'{i}. {s["title"]} | {s["role"]} | {s.get("minutes",0)} min | {s.get("evidence","-")} | {s.get("src","-")}' for i,s in enumerate(d['slides'],1)]
for k in('decisions','omitted','unresolved','qa'):
  L+=['## '+k]+['- '+(x if isinstance(x,str) else '; '.join(f'{a}: {b}' for a,b in x.items())) for x in d.get(k) or []]
open(o+'narrative_plan.md','w').write('\n\n'.join(L))
E
```

For people: `references/guide.md` has usage, method, limits and maintenance, and `examples/synthetic` for a complete input, spec and expected shape of the output (`python3 $S/deckkit.py selftest`). Same-input comparison with and without this Skill on local practice cases: `references/evidence.md` (not needed during a run).
