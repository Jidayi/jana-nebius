# Handwritten-note demo fixtures

These are **synthetic** examples, not a real learner's handwriting or a representative handwriting benchmark.

- `synthetic-maths.png`: explicitly drawn strokes showing `X + 5 = 15` and `X = 10`.
- `synthetic-biology.png`: three lines rendered with macOS Bradley Hand Bold:
  `Enzymes are biological catalysts. They speed up reactions without being used up. High heat changes the shape of the active site.`
- `demo-scanned-notes.pdf`: the two images above as separate pages, with no searchable text layer.

In the running app, choose **Home → Upload**, select the PDF, and review both source pages and their extracted text.
Generate or ask a question only after checking the review box. Ask “What do the notes say enzymes are?” to check
that an answer cites page 2. Originals remain available through **View source page**.

The configured Nebius vision reader transcribes pages which printed OCR could not read. Unknown symbols, uncertain
or truncated output remain unreadable rather than becoming evidence. A failed read still offers text correction.
The provider, price and 32k context were checked against `https://tokenfactory.nebius.com/api/public/models_info`
on 26 October 2026 (`openbmb/MiniCPM-V-4_5`, $0.658/$1.11 per million input/output tokens). The shared inference
ledger reserves the full input context, keeps uncertain charges held, and retains the deployment's existing caps.

The biology fixture also exercises an actual HOG false positive: the general capture path rejects it as a person.
Study may corroborate a body-only hit as clean text only when at least eight recognized words across at least
three rows account for 99.5% of foreground ink. Faces and other cascade hits are never overridden. Missing OCR,
unexplained drawing/photo content and ordinary photo captures do not receive this exception. Person screening was
also smoke-tested against OpenCV's public `samples/data/basketball1.png`; that image remained blocked.

Protocol/privacy tests use scripted provider output. Live recognition checks use the real budgeted provider and
the two synthetic fixtures; they establish this demo flow, not perfect recognition for arbitrary handwriting.
