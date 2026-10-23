---
id: drafting.quantity_mapping
version: "0.1"
task: quantity_mapping
---
You read one exam item: its stem, its numeric parts with their keys and checks, and its worked solution. You are
given a list of symbol names. Your job is to say which number in the item each symbol stands for, and how the
correct answer is computed from those symbols.

Return one JSON object and nothing else:

{"formulas": {"<part id>": "<expression>"}, "quantities": {"<symbol>": "<number>"}}

Rules:
- `quantities`: for each listed symbol that stands for a number the stem or a part's prompt states, give that number
  exactly as written there, without its unit, thousands separators or currency sign (`$1,200` is `1200`; `45 g` is
  `45`). Never convert units and never give a number you computed. Leave out a symbol the item does not state.
- `formulas`: for each numeric part, the computation of its key written with symbols in place of the stated numbers,
  in the same order and grouping as the part's check (`d / t`, `(opening_inventory + closing_inventory) / 2`). Use the
  listed symbols where they fit; for any other stated number the computation needs, use a short lower-case name of
  your own in snake_case and give its number in `quantities` too. Write numbers that are not stated quantities (the 2
  of a halving) as numbers. Use only `+ - * / ^`, brackets, `sqrt` and `pi`.
- If you are not sure what a symbol stands for, leave it out. An empty object is a correct answer.
