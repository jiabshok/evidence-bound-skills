---
name: slide-template-adaptation
description: Move an existing academic deck or content into a required PPTX template - real layout and placeholder inheritance, text fitting, native tables and charts, pictures, notes, footers, consistent sizes - with a loss audit, PDF export, deviation record and result.json. Use for template or format adaptation with /input holding a slide-workorder, target-template.pptx and usually starting-deck.pptx.
---

# Academic slide template and format adaptation

Use when content must be put into a given template without losing or changing it. Output in `/app/output`: presentation.pptx, presentation.pdf, previews/, contact_sheet.png, claim_source_map.csv (page-level evidence), change_record.json (preservation audit), speaker_plan.md, rebuild/, result.json.

**Never inspect `/app/output` with your own commands** (cat, sed, ls, python on result.json, edit_record.json, REPORT.md): every engine command prints what it found, `review` prints the claims, `verify` prints the final state. Each extra read costs 30-60 s of a 15-minute run.

## Adapt: the normal route (starting deck + target template)

Commands are `python3 $S/deckkit.py NAME`; begin each shell call with `S=/skills/weekly-skill/scripts;` (or the scripts directory beside this file).

1. `brief`, then at once `adapt`. It rebuilds every slide 1:1 (title, body levels, tables, native charts with data, pictures, groups, links, notes, hidden state) in real template layouts and audits the loss.
2. Read the output lines:
   - `ATTENTION` / `SLIDE n: ... does not fit`: fix with an override. `SLIDE n: chart ... copied as the original native chart` is information only.
   - `LEAD slide n: [..] not found`: a number in the deck that is nowhere in the material. `find` it and `show` the passage. Rounded, unit-converted or computed from source values: leave it. Otherwise the engine's lead is not enough: add an `unresolved` entry with both values and `src`. NEVER change the slide, unless the work order makes the material authoritative and asks for corrections (then log before -> after in `decisions`).
   - No LEAD does not prove agreement: run `audit` once and compare the deck's main numbers and claims with the material.
3. Only if needed write `/app/work/overrides.json` and rerun `adapt` (always restarts from the original deck). Example (invented content):

```json
{"footer":"Short footer","unresolved":[{"item":"Slide 4: maximum 12.3 %","state":"conflict","detail":"deck 12.3 %, material 11.2 %; slide left unchanged","src":["P008"]}],
 "decisions":["Slide 3: second sentence moved to notes, no room at 14 pt"],"omitted":[{"item":"Slide 3: full sentence","reason":"moved to notes"}],
 "3":{"bullets":[{"text":"First point, as printed","level":0},{"text":"detail","level":1}],"notes":"<complete original notes>\nmoved from slide: <full original sentence>"},
 "6":{"layout":"exact layout name","visual_side":"bottom"}}
```

Number keys are ORIGINAL slide numbers; per slide: `title`, `bullets`, `notes`, `layout`, `src`, `visual_side` (`right`/`bottom`, for a slide with text and a visual), `unhide` (true only if the work order says so). A key given REPLACES that part: list all bullets and the complete notes. Bullets must be objects, plain strings crash adapt. `src` prints a source line on the slide; without it the evidence map is matched automatically, so omit it when no text may be added. A misspelt layout name is silently ignored: check with `slide N`.

- Legibility in the room: a chart or figure that ends up small beside a long text block gets `visual_side: bottom` or a layout with a larger picture area, so it fills at least half of the slide; a slide that needs more space keeps its text and moves only the overflow to notes (logged).
- Preserve wording and numbers. Try `layout` / `visual_side` first; shorten only what cannot fit at the template's minimum, and log it as above. Never drop a slide, cell, series, image or note.
- After a deliberate shortening `content_preservation` stays open and status is `partial`. That is honest: explain it in `decisions`; do not loop.
- Count or order must change: finish `adapt`, `cp /app/output/change_record.json /app/output/adapt_change_record.json`, then run `edit` with `"continue":true` beside `"ops"` (works on the adapted deck; numbers = adapted deck). Put every `add_slide` BEFORE any `delete_slide`, else a slide can be overwritten. Rerun `adapt` before each rerun of `edit`. Write the mapping and "rebuild = adapt, then edit" in `decisions`.
- No starting deck: `build` with deck.json. No template: `build` uses the starting deck's master or a plain default; state it in `unresolved`.

**Last step.** After the last adapt, paste this once (keeps the rebuild input; writes adaptation_log.csv: slide, old and new layout, media, font changes, text not verbatim. Skip it after `edit`):

```bash
S=/skills/weekly-skill/scripts; mkdir -p /app/output/_work; cp /app/work/overrides.json /app/output/_work/ 2>/dev/null
sed -n '/^#adapt-log/,/^#end/p' $S/../references/guide.md | python3 -
```

## How this works

You write at most ONE small file (`overrides.json` for adapt, `deck.json` for build, `edits.json` for edit, all in `/app/work`). The engine fills real layouts and placeholders, fits text, makes native charts/tables, adds notes and footers, exports the PDF, re-reads the saved deck and writes a complete `result.json`. Apart from that log command, do not write your own python-pptx, export or JSON code, and do not read the engine source or the example files: everything you need is on this page.

| step | command | budget |
|---|---|---|
| 1 | `brief` - case, work order, layouts, starting deck, tables, passage ids; saves a first honest result.json | 1 call |
| 2 | adapt: run `adapt` now. Then `audit` (conflicts, n, percentages, limits, hedged statements), then `show P004-P012` / `find WORD` / `table FILE` / `slide N` - read what the slides need | 2-6 calls |
| 3 | write the spec file (adapt: only if something needs fixing) | 1-3 calls |
| 4 | `build`, `adapt` or `edit` (see mode) - fix each ATTENTION / SLIDE / SOURCE line, rerun | 1-4 calls |
| + | **`python3 $S/deckkit.py review`** after the content is complete - prints every claim next to the sentence it cites and the whole requirement list: correct wrong direction, sign, strength, condition, unit or citation; add every missing required item (use `show`/`table` to fetch it). It ends with POSSIBLY MISSING lines: close every real gap, rebuild, review again. Accuracy and completeness weigh far more than speed; watch the printed minutes: requested edit done by minute 8, verify by minute 10 (cut at 15; the model may be slow) | 2-5 |
| 5 | `read_image /app/output/contact_sheet.png` once; fix visible faults | 1-2 calls |
| 6 | `verify`, then stop | 1 call |

**Hard limit: one response (thinking + text + tool call) over 16384 tokens aborts the whole run.** Think briefly, decide once, and write early. For `build`, write `deck.json` with the top-level keys and the first 3-4 slides, then `slides_2.json`, `slides_3.json` ... (each a JSON list of the next 3-4 slides). Do not print whole files.

First `adapt` by call 3, first `build` before call 14 or minute 6. After it all deliverables exist. Stop when the work order is covered and each open check is explained.

## Decide the content (only `build` and added slides; when adapting, title wording, order and visuals stay as they are)

1. From the work order: mode, exact slide count, minutes, audience, language, rules about template, preservation and uncertainty. These override everything here.
2. Storyline: problem -> gap -> approach -> 2-4 key results -> limits -> message. One claim per slide; the title IS the claim as a full short sentence (max about 12 words). Explanation and caveats go to notes.
3. Strength: write "was associated with", "in this model", "proposed" exactly as strongly as the source. Not significant is not "no effect". Not reported stays "not reported". Illustrations and simulations are not measurements.
4. Every real conflict or gap in the `audit` leads that touches the talk becomes one `unresolved` entry with both values and passages (this one also for adapt); important ones go on the limits slide.
5. Numbers: copy as printed, with unit, n and interval. If text and table disagree, use the table value and record both in `unresolved` and in the notes.
6. Every slide and every factual bullet has `src`: passage ids (`"P012"`, `["P012","P015"]`), a data file (`"file.csv"`, `"file.csv#3-9"`) or `"workorder"`.
7. Half of the content slides carry a native visual or a supplied image; never redraw data you do not have.

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
- Markup: `*italic*`, `**bold**`, `_{sub}`, `^{sup}`.
- The slide count in the spec must equal the work order exactly (title, backup and Q&A slides count unless the work order says otherwise). Per-slide `minutes` must add up to the requested time (backup slides 0).

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

Ops run in the listed order. Slide numbers always mean the ORIGINAL numbering, whatever was added, moved or deleted before; `"after":"new1"` places a slide after one you added with that id; `to`/`position` is the final position at that moment, so put moves last. `replace_text`, `set_text`, `set_title` and `set_cell` keep the existing formatting (set_text copies the first paragraph's format). `edit` always starts again from the starting deck, so keep all ops in one file and rerun. Check with `slide N` (current output) instead of your own scripts. Make only requested changes; a chart and the text quoting it change together.

## If something goes wrong

- `SPEC ERRORS` / `CANNOT BUILD` / a traceback: nothing was overwritten. Fix the named entry; for `adapt`, check that overrides.json is valid JSON with object bullets. If it fails twice, remove overrides.json, run plain `adapt`, put the rest in `unresolved`.
- text/table/flow "does not fit": shorten, split, or move detail to notes.
- `numbers_traceable`: cite the passage that has the number or correct it; if computed, say "computed from ..." on the slide and give the formula in notes and `decisions`.
- template without a needed placeholder: the engine uses the closest layout and reports it; do not edit the master.
- fonts missing in the renderer: kept in the PPTX, substitution in the PDF is disclosed automatically.
- unreadable input, encrypted PDF, missing figure or PDF export failure: record in `unresolved` with what you tried; never fill the gap from memory.
- `verify` says INCOMPLETE (status partial) but files exist: not an error if each open check is explained; stop.

`result.json` is written by the engine with the contract fields; do not rewrite it. If a case contract has extra root fields, add them with a few lines of Python that load, set and save the file after the last build.

`references/guide.md`: usage, method, limits, maintenance. `examples/synthetic`: invented input and spec (`selftest` runs it). Same-input comparison with and without this Skill on local practice cases: `references/evidence.md` (not needed during a run).
