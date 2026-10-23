# pack-builder

The authoring toolchain (internal; D34): the content source tree, the `aut` command line, AI drafting with tool
verification, the automated pipeline gates (no human approval step, D65), preview packs, the coverage report and pack
builds. It never holds a signing key: publishing goes through `services/signing-service` (AUT-33).

Offline symbolic checks use `build_check_symbolic_slice_ms` (3,000 ms, bounded to 100–5,000 ms) and at most
`build_check_timeout_attempts` attempts (three by default). An exhausted check remains unknown and blocks the build.
The learner's `ver_symbolic_slice_ms` stays at 800 ms. A larger offline window allows exact trigonometric checks
to complete while preserving the source answer keys, tolerances and proof requirements.

```bash
uv run aut --json validate          # contract, identifiers, map and KCs
uv run aut --json verify            # every key, number and hint recomputed by the tools (CUR-20)
uv run aut --json lint              # licence gate, attribution, AI provenance, skill linter
uv run aut --json qa                # the automated content QA of TABLE CUR-25a (needs Node and pnpm install: KaTeX)
uv run aut --json scan              # the age-appropriateness content scan and sensitivity lint (PRV-17, CUR-27)
uv run aut --json coverage          # coverage per subject-level (CUR-31)
uv run aut --json build phy/o --out build/packs     # unsigned, reproducible build
uv run aut --json preview itm.phy.o.motion.0001     # unsigned preview pack
uv run aut --json ci --base origin/main             # the content CI gates (AUT-06)
```

Commands that change state act as an authoring account: set `JANA_AUTHOR` to your account id; banking and publishing
need the curriculum-lead role (no one-time code, D67). Accounts and the hash-chained audit log
live in the authoring home (`JANA_AUTHORING_HOME`, default `~/.jana/authoring`), never in the repository.

```bash
uv run aut edit itm.phy.o.motion.0001                       # register an edit you made to the file (a published
                                                            # mock paper using the item is edited with it, ASM-15)
uv run aut quantities --report q.json                       # item quantities for misconception signatures (CUR-18)
uv run aut quantities --propose gemini --env-file .env      # ... first ask the gateway's fast model for mappings no
                                                            # reading binds (cached, budget-capped; tools decide)
uv run aut quantities --write                               # ... saved as registered edits; then promote and bank
uv run aut draft hint_ladder itm.phy.o.motion.0001          # AI draft (local model via JANA_DRAFT_URL, else template)
uv run aut accept itm.phy.o.motion.0001 parts               # accept a verified AI field
uv run aut promote phy/o                                    # drafted records that pass every gate become verified
uv run aut bank phy/o                                       # verified records into the evaluation bank (CUR-22)
uv run aut publish phy/o --channel dev                      # a request queued for the signing service
```
