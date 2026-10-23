# Bake-off records

No model/device results are fabricated here. A release requires `<run_id>.record.json`, validated against
`record.schema.json`, wrapping the existing `harness.bakeoff.build` report. `release.bakeoff.record` captures the
candidate commit, exact frozen suite lock, prompt file versions/hashes and canonical input-result hash. Keep the raw
reference-device results with the release artifacts so the input hash can be independently reproduced.

Generate through `python -m jana_tools release bakeoff-record --input results.json --candidate <commit>
--run-id <id> --date <UTC timestamp> --weights-fixed-at <UTC timestamp> --out evals/bakeoff/<id>.record.json`.
All D6 candidates, filter outcomes, every role/tier/class and held-out confirmations are required. A record does not
change D6, the recommendations file, specification pins or any release acceptance status. Those decisions require
review of the real measurements.
