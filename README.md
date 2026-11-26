# Evidence-bound figure and slide Skills

Nine Agent Skills for scientific figures and academic slides. The agent writes a small specification; a deterministic engine draws, exports, reads the delivered files back and writes the result record. Nothing in the repository contains case answers.

| Folder | Task |
|---|---|
| `skills/graphical-abstract-7030fff2` | Graphical abstract |
| `skills/challenge-98e5a474` | Scientific schematic, create and edit |
| `skills/challenge-1bd90d8a` | Data chart, create and edit |
| `skills/challenge-83d4f050` | Biological mechanism / pathway |
| `skills/challenge-9034312d` | Apparatus and technical route |
| `skills/ppt-c7b80f0d` | Paper to slides |
| `skills/challenge-20870c35` | Presentation storyline |
| `skills/ppt-710fbc72` | Template adaptation |
| `skills/ppt-6ad93034` | Slide generation and editing |

## Use

Copy one folder into your agent's skill directory. Each folder is self-contained: `SKILL.md`, `scripts/`, `references/guide.md`, `examples/synthetic`.

```
python3 skills/challenge-83d4f050/scripts/figkit.py selftest
python3 skills/ppt-c7b80f0d/scripts/deckkit.py selftest
```

Requirements: Python 3.9+. Figures: Pillow optional; one of Playwright Chromium, CairoSVG, rsvg-convert, Inkscape or LibreOffice for PNG/PDF; poppler for PDF checks. Slides: python-pptx, lxml, Pillow, LibreOffice, poppler.

## Method in short

- `start` drafts the specification from the work order and hands the agent one requirement at a time (`next`) with the passages that answer it, so a small model never has to plan a whole figure in one response.
- Evidence strength controls the drawing: a relation whose every cited sentence only proposes it, correlates the two ends or reports earlier work is drawn dashed (sign kept) or grey and listed in `exceptions`.
- `fromtable` turns result-table rows into relations with value, sign, p and row-level source; `prune` removes a subset for an edit and lists it in an inset.
- `audit` finds malformed numbers, one value with two units, percentages that do not fit their counts, table/text p-values that differ; sure findings go to `exceptions` unrepaired.
- `review` prints every claim beside the sentence it cites, the requirement list, terms missing from the visible text, and values in the best passages of each requirement that the delivery lacks.

## What is checked, and how

| Check | Method |
|---|---|
| Chart values | geometry in the delivered SVG is inverted through the axis calibration and compared with the table cells |
| Entities and relations | re-parsed from the delivered SVG and compared with the specification as sets |
| Requirements | terms of each work-order line are searched in the visible figure/deck text; facts found only in captions or JSON are listed apart |
| Schedules | drawn on one calibrated time axis (`timeline` panel) with the stored start, end and time-point values |
| Numbers | every number printed is searched in the passage or rows it cites |
| Edits | element-by-element comparison with the frozen first version; untouched elements stay byte-identical |
| Template inheritance | canonical-XML hashes of master, layouts and theme before and after |
| Adaptation loss | both PPTX files are re-read independently: text, table cells, chart data, image hashes, notes, hyperlinks, hidden flags, groups |
| Untouched slides | deep hash of slide XML, notes, chart parts, workbooks and media |

Each Skill has `references/evidence.md`: same-input local runs with and without the Skill (practice cases, local judge, run time and requests), including the cases where the Skill did not raise the judged score.

Limits: schematics of about 6-25 nodes; no photorealistic drawing; no animation or SmartArt reconstruction; scatter charts in migrated decks need manual review; checks establish traceability and file integrity, not scientific truth.

MIT licence. Colours: Okabe-Ito. Icons are original.
