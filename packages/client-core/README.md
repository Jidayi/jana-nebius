# @jana/client-core

Client store, reducer, stream client (`src/stream`, Streaming layer), profile scope and learning controllers.

Practice retains the original answer body and idempotency key when its outcome is uncertain, so a retry can recover
the committed mark. Closing the profile or replacing the set drops that pending request. Manual mock submission
waits for every pending answer revision to save; a failed save retains the sitting and answers for retry.

`waitForJob` validates and polls accepted jobs until completion, propagates terminal failures, and supports cancellation
when the owning screen closes. Archive recovery uses it so request acceptance is never shown as a finished restore.

`AssessmentController` uses the model-free local assessment lifecycle, validates redacted question presentations,
keeps uncertain mutations with their original idempotency key and body, and clears all state on a profile change.

`SavedQuestionsController` validates local snapshots, retains uncertain writes for idempotent retry, and scopes its
list, selection and pending requests to the open profile. It has no send or recipient API.

`SessionNotesController` reads local generation status and referenced excerpts, handles private confirmation and
deletion, and drops all opened text on profile changes. Its reader strips unreferenced statements and redacts private
list entries. The optional session-note API additions are explicit adapters until canonical contract reconciliation.
