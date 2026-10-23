# Curriculum sources

The single source of truth for curriculum content (AUT-03). Every file is in canonical form (keys in contract order,
LF line ends, Unicode NFC); `aut edit` and the build keep it that way, so diffs show real changes only.

| Path | Holds |
| --- | --- |
| `<subject>/<level>/pack.yaml` | The pack fields an author sets (id, version, channel, languages) |
| `<subject>/<level>/map.yaml` | Curriculum nodes |
| `<subject>/<level>/kcs/<topic>.yaml` | Knowledge components of one topic, with their prerequisite edges |
| `<subject>/<level>/{items,worked-examples,misconceptions,lessons,templates,diagrams}/<id>.yaml` | One record per file, named by its id |
| `ref/<subject>-<level>/conventions.yaml` | The pack's conventions and constants |
| `ref/acc-o/chart-of-accounts.yaml` | The `pack.ref` chart of accounts (CUR-07) the accounting answers and checks name (`acc.chart_of_accounts`); the accounting pack carries it in its `charts_of_accounts` table |
| `ref/common/context.yaml`, `ref/common/scan.yaml` | `pack.ref` word lists: local-context names, places and currencies (CUR-25), and the content scan's word lists (PRV-17, CUR-27) |
| `safety-reviews/<pack id>/<version>.json` | Signed content safety reviews of a release's sample (CUR-27), required by the signing service for pilot and stable |
| `review/<record id>.jsonl` | Review records, one JSON line per action, hash-chained (AUT-23) |

Held-out evaluation items are never here: they live encrypted under `evals/held-out/` (CUR-22, EVL-18).

The physics map follows the structure of D59: topic structure and numbering follow the Cambridge O Level Physics
syllabus (5054), kept only as external mappings; every title, description and item is our own wording. Topic exam
weights are estimates for the subject lead to confirm (CUR-03). The S1 topic (motion in a straight line) was published
first; the rest of the O level pack was first drafted by a generator (below). Every record was drafted with AI and
verified by the build's tools (CUR-20, D65).

## The records are the source of truth (generators retired, 2026-10-15)

The Physics and Mathematics O level records were first drafted by generators (`scripts/content/phy_o/gen.py` and
`scripts/content/mth_o/gen.py`, last present at commit 3415e509). They were retired on 2026-10-15 (G113, CUR-16)
because the YAML records here, not the generators, are now the source of truth (AUT-03), and no generator can
reproduce them:

- every record has since moved through the pipeline (`verified`, `in_eval_bank`, `published`; CUR-19), and that state
  lives only in the records;
- the M13 content fixes edited about 350 Mathematics records (items, worked examples, KCs with their glossaries,
  misconceptions and a lesson) under new record versions, which the generator never had;
- the Physics generator refuses to run at all once its misconceptions are published (it never rewrites a published
  record), and a full Mathematics run would reset 1,546 published items to `verified` and undo the fixes.

New or changed records go through `aut edit`, the studio or a new drafting script, and through the same gates and
pipeline as every other record. A drafting script writes new records only; it never rewrites a record that has left
`verified` (as `scripts/content/mock_papers/gen.py` does, with its `--check` mode).
