# Presenting VibeFinder 2.0 from VS Code

## Before you present (one time, about 2 minutes)

1. **File → Open Folder…** and choose this project folder.
2. If VS Code asks to install the recommended extensions (Python, Python Debugger), click **Install**.
3. **Terminal → Run Task… → Set up (create .venv and install requirements)**.
4. If VS Code asks which Python interpreter to use, pick the one in `.venv`.
5. Do a dry run: **Terminal → Run Task… → Run tests** should end with `33 passed`.

## The demo, in slide order

Open the **Run and Debug** panel (`Cmd+Shift+D`), pick a configuration from the dropdown at the top, and press **F5** (or the green ▶).

| Slide | Run configuration | What to point out |
|---|---|---|
| Demo 1 · Retrieval | `1 · Retrieval: rainy night drive` | No genre in the request; `signal: genre 'synthwave' inferred from knowledge base` |
| Demo 2 · Guardrails | `2 · Guardrails: gym no pop, injection, off-topic` | No pop songs; `BLOCKED`; `NEEDS_CLARIFICATION` |
| Demo 3 · Self-check | `3 · Self-check: broken generator` | Red `CHECK failed` lines, blue `REPAIR #1`, green `CHECK passed` |
| The case I left failing | `4 · Stretch: energy limit (fall asleep)` | `RETRIEVE energy limit (low) kept 17/60 songs`; highest energy is 0.28 |
| Stretch | `5 · Stretch: typo fixes` | `chil -> chill, jazzz -> jazz`; "reading" is left alone |
| Reliability | `6 · Reliability: 13-case evaluation` | `13/13 cases passed` |
| Reliability | `🧪 Unit tests (pytest)` | `33 passed` |
| Web app | `🎧 Web app (Streamlit)` | Opens http://localhost:8501 in your browser |

To run everything in one go, use **`🎬 Full narrated demo (all scenes)`** and press Enter between scenes.

## Showing the code

- **The backbone:** `src/agent.py`, method `run()`. The seven steps are marked `# 1. GUARD` through `# 7. CONFIDENCE`.
- **Step through it live:** click in the left margin of `src/agent.py` next to `def run` to set a red breakpoint dot. Then run **`🔍 Step through the agent`**. Use **F10** to step over a line. The **Variables** panel shows `profile`, `candidates` and `picks` as they fill in.
- Quick jumps with `Cmd+P`: `agent.py`, `parser.py`, `guardrails.py`, `recommender.py`, `app.py`.

## Taking audience requests

Run **`💬 Interactive CLI`** and type any request at the `>` prompt, for example `upbeat hip hop, energy 0.7` or `music for a beach day, no reggae`. Press Enter on an empty line to stop.

## If something goes wrong

- **"No module named streamlit"**: rerun the **Set up** task, then choose the `.venv` interpreter (`Cmd+Shift+P` → *Python: Select Interpreter*).
- **Port 8501 already in use**: stop the old app with `Ctrl+C` in its terminal, or click the trash icon on that terminal.
- **Text too small for a projector**: `Cmd+=` zooms VS Code in.
