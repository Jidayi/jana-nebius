# @jana/ui

UI primitives, learning screens, design tokens (generated from the specification's tokens) and the gallery.
May import only `client-core`, `contracts-ts` and `i18n`; never an HTTP client or model SDK (ARC-18, ARC-19).

The shared lesson, practice and mock answer inputs support numeric, choice, ordering, algebraic and equation-solution
answers. Algebra accepts an expression or LaTeX; equation solutions are comma-separated values. Mock restoration
preserves both answer types and their working. The gallery includes light and dark examples and mock save recovery.

`AssessmentPlace` and `AssessmentContent` cover diagnostic introduction, answering, saved/resumed work, early stop,
outcomes and the mastery check's spaced waiting and retry dates. Their gallery fixtures cover both themes and text scales.

Subject-specific answer fields cover chemical equations (including state symbols), journal entries, accounting tables, numbered diagram labels and short text. Typed drafts and mock restoration use the same adapters as practice and lesson checks. Accounting rows keep partial entries; short text respects the core-provided character limit. Item visuals render through the registered visual renderer.

The transcript windows sessions over 40 turns with measured spacers. Its local height cache includes content signatures, width and text scale, and is discarded with the conversation. Live/open/focused/reading rows stay mounted. Find searches stored messages and text, and navigation explicitly captures the requested anchor before measurement updates can restore a prior position. The 500-turn DOM regression is supplemented by the desktop gallery's browser replay.
