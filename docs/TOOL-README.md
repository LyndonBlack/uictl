# uictl

Offline, stdlib-only UI automation CLI for apps with no scripting dictionary and no API.
macOS (Accessibility via System Events/JXA) and Windows (.NET UI Automation via PowerShell), one selector language, one action-file format.
No network calls, no telemetry, no third-party packages. Python >= 3.9.

**Status: v0.1.0 bones.** Core, runner, CLI and mock backend are tested (18 unit tests, Linux).
The macOS and Windows backends are written but **not yet run on real machines** — see docs/PLAN-AND-WRITEUP.md.

## Try it anywhere (mock backend)
    python3 -m uictl --backend mock --mock-tree examples/mock_app.json inspect DemoApp
    python3 -m uictl --backend mock --mock-tree examples/mock_app.json -v run examples/export.action.json -p path=/tmp/x
    python3 -I -m unittest discover -s tests -t .

## On the Mac / Windows box
    python3 -m uictl apps                      # is the app visible?
    python3 -m uictl inspect "MyApp" --flat    # map the UI once; --save tree.json to keep it
    python3 -m uictl find "MyApp" "role=button,title=Export"
    python3 -m uictl click "MyApp" "role=button,title=Export"
    python3 -m uictl --dry-run run my.action.json -p path=/tmp/x
    python3 -m uictl repl
macOS: grant Accessibility to the terminal/launcher app (System Settings > Privacy & Security).
Windows: needs Windows PowerShell 5.1 with Add-Type allowed (not Constrained Language Mode); cannot drive elevated apps from a non-elevated shell.

## Concepts
- **Selector**: `role=button,title=Export` or JSON. Keys: role, title, title_contains, title_re, value, value_contains, id, enabled, index, first, within (scope to a sub-selector). Roles are normalised (AXButton / ControlType.Button -> `button`) so action files port across OSes. Ambiguous matches are an error unless you say `index`/`first`/`within`.
- **Action file** (JSON): named params, ordered steps. Ops: click, type, keys, key, focus, activate, get, wait, assert, sleep. Every step can carry `expect` (post-conditions: exists / gone / enabled / value), `pre`, `retries`, `timeout`. Retries back off 1s, 2s, 5s. `{param}` substitution; literal braces must be doubled `{{ }}`.
- **Guard**: the runner snapshots, selects, then tells the backend to act on a path *and* what role/title it expects there; the backend refuses if the tree shifted in between.
- **--dry-run** resolves selectors without acting (steps that depend on windows an earlier step would open report `unresolved`).
- **--json** on every command.

## Adding a backend
Implement `uictl/backends/base.py::Backend` (six primitives). Everything else is shared.
