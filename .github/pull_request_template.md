## Summary

<!-- What changes and why, in a few lines. Cite requirement IDs; never paste specification text. -->

Requirements:
Tests made green:

## Feature review

<!-- PRV-01: name the minors-first principles (LIST PRV-01a, items 1-9) this change affects and how each is
     satisfied. Required for changes to learner, personal-service or safety code paths; otherwise "none". -->
PRV-01a items affected: none

<!-- PRD-20: list any non-goal (LIST PRD-20a, items 1-10) this change touches, with the decided decision ID that
     allows it. A non-goal without a decided decision is rejected. -->
Non-goals touched: none

<!-- PRD-02: if this change trades one principle against a later one, say which and why. -->
Declared trade-off: none

## Checks

- [ ] Code stays inside its declared layer; generated files changed only by codegen
- [ ] Tests named after the requirement's acceptance tests
- [ ] User-facing copy keyed, never literal; traces and redaction on any new data path
- [ ] Offline job, contract staleness and layer check green
