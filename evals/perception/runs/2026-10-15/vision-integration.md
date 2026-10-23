# Evaluation run evr_20261014T235625_85a847 (development)

Build 0.0.0 at 49871a478243 · high class on darwin · network disabled, 0 egress attempts · valid

| Suite | Version | Status | Passed | Rate (95% interval) |
| --- | --- | --- | --- | --- |
| answer_oracles | 2026-10-14.2 | not_selected | 0/0 | - |
| classification | 2026-10-09.1 | not_selected | 0/0 | - |
| content_packs | 2026-10-14.2 | not_selected | 0/0 | - |
| learning_gain | 2026-10-09.1 | not_selected | 0/0 | - |
| marking | 2026-10-13.1 | not_selected | 0/0 | - |
| mastery_model | 2026-10-09.1 | not_selected | 0/0 | - |
| memory_recall | 2026-10-13.1 | not_selected | 0/0 | - |
| pedagogy_rubric | 2026-10-13.1 | not_run_needs_model | 0/0 | - |
| perception (fixture assertions) | 2026-10-15.1 | ran | 176/180 | 97.8% (94.4% to 99.1%) |
| performance | 2026-10-13.1 | not_run_device_lab | 0/0 | - |
| prompt_regression | 2026-10-13.3 | not_selected | 0/0 | - |
| safety | 2026-10-14.2 | not_selected | 0/0 | - |
| scenarios | 2026-10-14.3 | not_selected | 0/0 | - |
| simulated_students | 2026-10-13.1 | not_run_needs_model | 0/0 | - |
| skill_evals | 2026-10-13.2 | not_selected | 0/0 | - |
| ui_gallery | 2026-10-14.2 | delegated | 0/0 | - |

Printed exact transcription: 18/22 fixture photos.
Rendered development fixtures are not ordinary-camera EVL-12 or reference-device acceptance evidence.

Failed cases:
- perception/chemistry-plain::exact_transcription: Transcription differs: 'How many atoms are in H2O?\n[?]'
- perception/accounting-tilted::exact_transcription: Transcription differs: 'Prepare a journal:\nDr Cash 100; Cr Sales 100.\nNo diagram is present.'
- perception/privacy-name::exact_transcription: Transcription differs: 'Find x if\n2x + 5 = 15.\nFind x if 2x + 5 = 15.\nA white rectangular box is located at the top left of the image.'
- perception/privacy-contact::exact_transcription: Transcription differs: 'Find x if \\( 2x + 5 = 15 \\).\nwhite rectangle\nA white rectangular box located at the top of the image.'
