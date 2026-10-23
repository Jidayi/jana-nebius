#!/bin/sh
# Guard: the Jana specification must never enter this (public) repository.
# The spec lives in docs/, a separate local-only git repository.
#
#   check-no-spec.sh staged          pre-commit: check the staged changes
#   check-no-spec.sh range A..B|SHA  pre-push: check commits being pushed
#   check-no-spec.sh tree            CI: check the whole checked-out tree
#
# Blocks (1) any path under docs/ and (2) text that only the spec contains:
# requirement headings, requirement metadata lines and numbered spec tables.
PATTERN='^#{2,4} [A-Z]{2,4}-[0-9]{2,3}[a-z]? — |^Stage: S[0-5] · Priority: |^(TABLE|FIGURE|LIST) [A-Z]{2,4}-[0-9]{2,3}[a-z] — '
SELF='scripts/git-hooks/check-no-spec.sh'
fail() { echo "no-spec guard: $1" >&2; exit 1; }

case "$1" in
  staged)
    paths=$(git diff --cached --name-only)
    added=$(git diff --cached -U0 -- . ":(exclude)$SELF" | grep '^+' | grep -v '^+++' | cut -c2-) ;;
  range)
    paths=$(git log --format= --name-only "$2")
    added=$(git log -p --format= -U0 "$2" -- . ":(exclude)$SELF" | grep '^+' | grep -v '^+++' | cut -c2-) ;;
  tree)
    paths=$(git ls-files)
    added=$(git ls-files -z | grep -zv "^$SELF\$" | xargs -0 cat 2>/dev/null) ;;
  *) fail "usage: check-no-spec.sh staged|range <rev-range>|tree" ;;
esac

echo "$paths" | grep -Eq '^docs(/|$)' && fail "a path under docs/ is included; the spec is local-only."
echo "$added" | grep -Eq -- "$PATTERN" && fail "specification text (requirement headings or metadata) found; keep it in the local docs repository."
exit 0
