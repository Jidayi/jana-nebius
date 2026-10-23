# Jana S0 prototype (frozen)

This is the S0 prototype, moved here in M0. It is frozen: no new work lands here, and it is excluded from every release. Run it from this folder.

Jana is a step-by-step tutor that runs **entirely on your computer**. The model runs in [Ollama](https://ollama.com), and nothing you type or upload leaves the machine.

## Features
- Step-by-step solutions with LaTeX rendered by KaTeX, ending in a boxed final answer
- Subjects: **Maths, Physics, Chemistry, Biology, Accounting**, each with its own tutor prompt
- Levels: **O level / A level** switch; explanations and quizzes are pitched to the chosen level
- **Photo input**: drag-drop, paste (⌘V) or 📷. Uses a vision model; if the selected model can't read images, the app switches to an installed one that can
- **Graphs**: the model can emit a `graph` block, which is plotted with function-plot
- **Interactive quizzes** ("Quiz me"), built with Ollama structured output (JSON schema)
- Shows the model's reasoning ("Show reasoning") for thinking models
- Math symbol keyboard, follow-up chips, recent chats saved in the browser, Stop button, tokens/sec
- Works fully offline after setup (KaTeX, marked and function-plot are served locally)

## Setup
```bash
ollama pull qwen3-vl:8b        # vision + math, ~6 GB (good default)
npm install
npm start                      # opens http://localhost:5178
```
Or double-click **Start Jana.command**.

### Model suggestions
| Model | Size | Notes |
|---|---|---|
| `qwen3-vl:8b` | ~6 GB | Reads photos, good at math, fast. Recommended default |
| `qwen3-vl:30b` | ~20 GB | Stronger reasoning and photo reading (needs ≥32 GB RAM) |
| `gpt-oss:20b` | ~14 GB | Very strong step-by-step math. Text only (pair it with a vision model for photos) |
| `qwen3:8b` / `qwen3:30b` | 5–19 GB | Text-only reasoning models |

Pick the model in the sidebar. The app reads each model's capabilities (vision and thinking) from Ollama.

## Config
- `PORT`: default 5178
- `OLLAMA_HOST_URL`: default `http://127.0.0.1:11434`
- `NO_OPEN=1`: don't auto-open the browser

## Contributing
The product specification is kept in a separate, private repository and must never be committed here. After cloning, enable the guard hooks once:
```bash
git config core.hooksPath scripts/git-hooks
```
The same check runs in CI (`.github/workflows/no-spec.yml`), so a push that contains specification text fails there too.

## Structure
```
server.js         zero-dependency Node server: static files + /ollama proxy (localhost only)
public/index.html UI shell
public/app.js     chat, streaming, math/markdown rendering, graphs, quizzes, photos
public/style.css  light/dark theme
```
