# CLI-Anything review -> uictl: plan, results, roadmap

## 1. Goal
A small CLI to drive an internal desktop app that has no scripting dictionary, API, or file/db access, on a locked-down machine with
no outbound calls. Accessibility/UI Automation is the only route, so the design priority is *making fragile UI scripting
verifiable and repeatable*. Must be cross-platform (macOS now, Windows possible).

## 2. What CLI-Anything turned out to be
A methodology (HARNESS.md) plus a generator plugin that has an LLM agent build one Click CLI per target app, assuming the app has a
real backend to call (a binary, API, or scripting interface). That assumption is exactly what fails for us, so we did not fork it.
Only one component targets UI-only apps: `macrocli`, with 7 backends (native API, file transform, coordinate macros, template
matching, accessibility via osascript/AT-SPI/pywinauto, and two vision-LLM backends that call HTTP).
The `cli-hub` package is the phone-home part: PostHog/Umami telemetry fires at startup, plus registry fetches and pip/npm installs.
Core harness code itself (REPL skin, session, SKILL generator) is network-free.

## 3. What I built (`~/AI/uictl`, v0.1.0)
| Piece | State |
|---|---|
| model.py: node/selector language, role normalisation, `within`, ambiguity errors | tested |
| runner.py: select -> guard -> act -> verify, expect/pre conditions, retries with 1/2/5s backoff, params, `get` variables, dry-run | tested |
| cli.py: apps / inspect / find / click / type / keys / key / wait / run / repl, `--json` everywhere | tested |
| backends/mock.py: scripted in-memory app (runs on any OS, used by tests) | tested |
| backends/macos.py: JXA over `osascript` -> System Events AX tree | request/parse logic tested with a fake runner; JXA syntax-checked with node; **never run on a Mac** |
| backends/windows.py: PowerShell + System.Windows.Automation | request/parse logic tested with a fake runner; **PowerShell never executed** |
| examples/, 18 unit tests, README | done |

Deviations from the original: stdlib only (argparse not Click, JSON not YAML, unittest not pytest), zero dependencies, no network anywhere.
One bug found and fixed while testing (path tuple/list mix in `within`), plus a design fix: dry-run reports dependent steps as `unresolved`.

## 4. Known risks (be honest)
- **Untested on real OSes.** Expect first-run fixes in JXA property access and the PowerShell script. First thing to do on the Mac: `uictl apps`, then `inspect` on any app.
- **Apps that expose a poor AX tree** (custom-drawn, Electron without accessibility, Java/Qt without bridges) will show empty or generic nodes. `inspect` tells you in a minute; if so, the fallback is image-template matching (see salvage: visual_anchor.py).
- **Speed:** each AX property read is an Apple Event; deep trees take seconds. `--depth` limits it. A Swift helper would be ~100x faster (option below).
- **Windows:** Constrained Language Mode blocks Add-Type; elevated apps need an elevated shell; SendKeys is crude.
- **Locale:** selecting by title breaks if the UI language changes; prefer `id` (AXIdentifier / AutomationId) where the app sets them.
- Substitution uses `str.format`: literal braces in action files must be doubled.

## 5. Where it could go
1. **v0.2 on real hardware:** validate backends, fix what breaks, record a real action file for your app.
2. **Swift helper (macOS)** compiled with `swiftc` on the Mac: AXUIElement directly, one process, fast tree walks, handles `AXObserver` waits instead of polling. Python keeps the same Backend interface.
3. **Fallback ladder** (from macrocli/routing+recovery): AX -> image template -> window-relative coordinates, selectable per step.
4. **Recorder:** `uictl record` logs your clicks, resolving each to a selector (AX hit-test) to draft an action file.
5. **Screenshot / OCR assertions** via built-in tools (macOS `screencapture` + Vision, Windows .NET) as extra `expect` types.
6. **SKILL.md generation** per action file so an agent can drive it (reuse the salvage skill_generator).
7. **Local server mode** (loopback or unix socket) if the restricted environment wants a long-lived process.
8. Session locking/undo for action files that mutate state (salvage session.py).

## 6. Keep vs throw away
**Keep (in `~/AI/cli-anything-salvage`):** HARNESS.md methodology; repl_skin.py; skill_generator + template; session-locking/auto-save/skill-generation guides;
gimp session.py; macrocli macro_model/runtime (postconditions), routing/base/recovery (fallback ladder); semantic_ui.py and visual_anchor.py as reference implementations.
**Throw away:** cli-hub (telemetry + registry), cli-hub-meta-skill, registries, macrocli's gui_agent/llm_assist/parameterize (HTTP to LLM APIs), all ~100 per-app harnesses (each assumes a real backend),
CI/PyPI/publishing machinery, npm/MCP-based backends (domshell, safari-mcp).
**Idea worth stealing even if we never reuse code:** verify-after-act (post-conditions per step). It is the single thing that makes UI scripting trustworthy.

## 7. Needed from you to proceed
Run the quickstart on the Mac and paste back `inspect --flat` output (sanitised) for any app, then for the internal app. That tells us immediately how good the AX tree is.

## 8. Repository
Fork of HKUDS/CLI-Anything at commit 34f5195. `main` mirrors upstream (kept so upstream can be diffed/merged); the `uictl` branch
(default) removes all upstream content except `LICENSE` and the vetted files in `salvage/`. Upstream history remains in git for reference;
the `cli-hub` telemetry code exists only in that history, not in the working tree. Paths in the sections above that mention
`~/AI/cli-anything-salvage` now live under `salvage/`.
