# uictl — offline UI automation CLI

Fork of [HKUDS/CLI-Anything](https://github.com/HKUDS/CLI-Anything), cut down to a small, stdlib-only, no-network tool for
driving desktop apps that have **no scripting dictionary, API or file access**, on locked-down machines.
macOS (Accessibility via JXA/`osascript`) and Windows (.NET UI Automation via PowerShell) behind one selector language.

> **Status v0.1.0 (bones).** Core, runner, CLI, mock backend: 18 unit tests pass. macOS/Windows backends are written but
> **not yet run on real machines**.

## Layout
| Path | Contents |
|---|---|
| `uictl/` | the package (model, runner, cli, backends: macos, windows, mock) |
| `tests/`, `examples/` | unit tests; mock app + sample action file |
| `salvage/` | unmodified upstream parts kept for future use (network-vetted), with an index |
| `docs/PROJECT.md` | project doc: goal, design, status, risks, roadmap, keep/discard |
| `docs/TOOL-README.md` | usage reference |
| `NOTICE`, `LICENSE` | Apache-2.0 attribution |

Branches: `main` is an untouched mirror of upstream; `uictl` (default) is this project.

## Quick try (any OS)
    python3 -m uictl --backend mock --mock-tree examples/mock_app.json inspect DemoApp
    python3 -m uictl --backend mock --mock-tree examples/mock_app.json -v run examples/export.action.json -p path=/tmp/x
    python3 -I -m unittest discover -s tests -t .

See `docs/PROJECT.md` and `docs/TOOL-README.md`.
