# Edit and adapt modes

Read this only when the work order wants the supplied starting deck changed in place (`edit`) or moved into another template (`adapt`).

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

Ops run in the listed order. Slide numbers always mean the ORIGINAL numbering, whatever was added, moved or deleted before; `"after":"new1"` places a slide after one you added with that id; `to`/`position` is the final position at that moment, so put moves last. `replace_text`, `set_text`, `set_title` and `set_cell` keep the existing formatting (set_text copies the first paragraph's format). `edit` always starts again from the starting deck, so keep all ops in one file and rerun. Check with `slide N` (current output) instead of your own scripts. Make only requested changes; a chart and the text that quotes it must change together; record anything inconsistent you were not asked to change in `unresolved`.

`goal`, `audience`, `storyline`, `qa`, `decisions`, `omitted` and `unresolved` go to the top level of edits.json and reach result.json; the Q&A list in `speaker_plan.md` and the plan-file snippet are for `build` only.

## adapt

`python3 $S/deckkit.py adapt` migrates the starting deck slide by slide into the target template and audits that no text, table, chart data, image, note or link is lost. No spec is needed. Optional `/app/work/overrides.json` may hold `footer`, `decisions`, `omitted`, `unresolved`. It does not carry `goal`, `audience`, `storyline` or `qa`: put what the speaker needs into `decisions`.
