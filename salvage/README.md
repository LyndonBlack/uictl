# cli-anything-salvage

Selected parts of HKUDS/CLI-Anything (Apache-2.0, see LICENSE) kept for future projects.
Source clone: ~/AI/CLI-Anything (commit 34f5195). Nothing here phones home.

**Vetting done:** grep for network imports/URLs/telemetry across every .py file here; the only hits are install-hint
strings (`pip install`, `npx skills add` in repl_skin.py:134). `parameterize.py` (OpenAI client) was removed.
These are *reference/reusable parts*, not a runnable package: several import the original `cli_anything.*` namespace and need light adaptation.

| Path | What it is | Deps | Notes |
|---|---|---|---|
| plugin/repl_skin.py | Branded REPL (prompt, history, banners, tables) | stdlib (prompt_toolkit optional, falls back to input()) | Strip the `npx skills add` hint string |
| plugin/skill_generator.py + templates/SKILL.md.template | Generates SKILL.md for agent consumption | stdlib (jinja2 optional) | Strip `pip install cli-anything-*` text |
| plugin/HARNESS.md | The methodology (7 phases) | doc | Mentions `npx domshell` only in the browser section |
| guides/session-locking.md, auto-save-dry-run.md, skill-generation.md | Practical patterns | doc | |
| gimp-session/session.py | Undo/redo + locked JSON session save | stdlib (fcntl: POSIX only) | Needs msvcrt shim for Windows |
| macrocli/macro_model.py, runtime.py | Macro/step model, postcondition checker | PyYAML, psutil | Best verify-after-act ideas; uictl's runner is the simplified descendant |
| macrocli/routing.py, base.py, recovery.py | Backend priority ladder, Backend ABC, retry+fallback | stdlib | Candidate for uictl v0.2 (AX -> image -> coords fallback) |
| macrocli/semantic_ui.py | osascript/AT-SPI/pywinauto control by label | pyatspi/pywinauto (optional) | Reference only; docstring claims pyobjc but it is osascript |
| macrocli/visual_anchor.py | Template-match click, window-relative coords | mss, numpy, Pillow, pynput | Offline, but heavy deps; the fallback to build if AX fails on your app |

**Deliberately excluded (network/telemetry/irrelevant):** cli-hub/ (PostHog+Umami telemetry, registry fetches), cli-hub-meta-skill/,
registry.json, matrix_registry.json, macrocli gui_agent.py + llm_assist.py + parameterize.py (OpenAI-compatible HTTP),
.github/, per-app harnesses (gimp, blender, ...), preview_bundle.py.
