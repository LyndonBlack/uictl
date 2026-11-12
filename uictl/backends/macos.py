"""macOS backend: Accessibility via System Events, driven with JXA through `osascript`.

No third-party code, no network. Needs the controlling app (Terminal/iTerm/your launcher)
to be granted Accessibility in System Settings > Privacy & Security.
UNTESTED on a real Mac as of v0.1.0 (written on Linux): validate with `uictl inspect`.
"""
from __future__ import annotations
import json
import subprocess
from .base import Backend, parse_combo
from ..model import UictlError, norm_role

_KEYCODES = {"return": 36, "enter": 76, "tab": 48, "space": 49, "delete": 51, "backspace": 51,
             "escape": 53, "esc": 53, "left": 123, "right": 124, "down": 125, "up": 126,
             "home": 115, "end": 119, "pageup": 116, "pagedown": 121}
_USING = {"cmd": "command down", "ctrl": "control down", "alt": "option down", "shift": "shift down"}

JXA = r"""
function run(argv) {
  var req = JSON.parse(argv[0]);
  var se = Application('System Events');
  function out(o) { return JSON.stringify(o); }
  function g(f) { try { return f(); } catch (e) { return null; } }
  try {
    if (req.cmd === 'apps') {
      return out({ok: true, apps: se.processes.whose({backgroundOnly: false}).name()});
    }
    var proc = se.processes.byName(req.app);
    if (!g(function () { return proc.exists(); })) return out({ok: false, error: 'process not running: ' + req.app});
    function props(el) {
      var p = g(function () { return el.position(); }), s = g(function () { return el.size(); });
      return {
        raw_role: g(function () { return el.role(); }),
        title: g(function () { return el.title(); }) || g(function () { return el.name(); }) || g(function () { return el.description(); }),
        value: g(function () { var v = el.value(); return (v === null || v === undefined) ? null : String(v); }),
        id: g(function () { return el.attributes.byName('AXIdentifier').value(); }),
        enabled: g(function () { return el.enabled(); }),
        bounds: (p && s) ? [p[0], p[1], s[0], s[1]] : null
      };
    }
    function walk(el, depth) {
      var n = props(el); n.children = [];
      if (depth < req.depth) {
        var kids = g(function () { return el.uiElements(); }) || [];
        for (var i = 0; i < kids.length; i++) n.children.push(walk(kids[i], depth + 1));
      }
      return n;
    }
    if (req.cmd === 'snapshot') {
      var root = {raw_role: 'AXApplication', title: req.app, value: null, id: null, enabled: true, bounds: null, children: []};
      var tops = g(function () { return proc.uiElements(); }) || [];
      for (var i = 0; i < tops.length; i++) root.children.push(walk(tops[i], 1));
      return out({ok: true, tree: root});
    }
    if (req.cmd === 'activate') { proc.frontmost = true; delay(0.2); return out({ok: true}); }
    if (req.cmd === 'keys') { proc.frontmost = true; delay(0.15); se.keystroke(req.text); return out({ok: true}); }
    if (req.cmd === 'combo') {
      proc.frontmost = true; delay(0.15);
      var using = req.using.length ? {using: req.using} : {};
      if (req.code !== null) se.keyCode(req.code, using); else se.keystroke(req.char, using);
      return out({ok: true});
    }
    if (req.cmd === 'act') {
      var el = proc;
      for (var j = 0; j < req.path.length; j++) {
        var kids2 = el.uiElements();
        if (req.path[j] >= kids2.length) return out({ok: false, error: 'path no longer exists'});
        el = kids2[req.path[j]];
      }
      if (req.guard) {
        var pr = props(el);
        if ((req.guard.raw_role && pr.raw_role !== req.guard.raw_role) ||
            (req.guard.title !== null && (pr.title || '') !== (req.guard.title || '')))
          return out({ok: false, error: 'element changed (guard mismatch): now ' + pr.raw_role + ' ' + pr.title});
      }
      if (g(function () { return el.enabled() === false; })) return out({ok: false, error: 'element is disabled'});
      if (req.action === 'click') {
        try { el.actions.byName('AXPress').perform(); } catch (e) { el.click(); }
      } else if (req.action === 'set_value') {
        el.value = req.arg;
      } else if (req.action === 'focus') {
        el.focused = true;
      } else return out({ok: false, error: 'unknown action ' + req.action});
      return out({ok: true});
    }
    return out({ok: false, error: 'unknown cmd ' + req.cmd});
  } catch (e) { return out({ok: false, error: String(e)}); }
}
"""


class MacOSBackend(Backend):
    name = "macos"

    def __init__(self, runner=None, timeout=60, **_):
        self._runner = runner or self._osascript
        self.timeout = timeout

    def _osascript(self, req):
        try:
            p = subprocess.run(["osascript", "-l", "JavaScript", "-e", JXA, json.dumps(req)],
                               capture_output=True, text=True, timeout=self.timeout)
        except FileNotFoundError:
            raise UictlError("osascript not found: this backend only runs on macOS")
        except subprocess.TimeoutExpired:
            raise UictlError("osascript timed out after %ss (app hung or Accessibility prompt pending?)" % self.timeout)
        if p.returncode != 0:
            raise UictlError("osascript failed: %s" % (p.stderr.strip() or p.stdout.strip()))
        return p.stdout

    def _call(self, req):
        raw = self._runner(req)
        try:
            data = json.loads(raw)
        except ValueError:
            raise UictlError("unparseable osascript output: %r" % raw[:200])
        if not data.get("ok"):
            raise UictlError(data.get("error", "unknown error"))
        return data

    def is_available(self):
        import sys
        return sys.platform == "darwin"

    def list_apps(self):
        return self._call({"cmd": "apps"})["apps"]

    def snapshot(self, app, depth=8):
        tree = self._call({"cmd": "snapshot", "app": app, "depth": depth})["tree"]

        def fix(n):
            n["role"] = norm_role(n.get("raw_role"))
            for c in n.get("children", []):
                fix(c)
        fix(tree)
        return tree

    def act(self, app, path, action, arg=None, guard=None):
        g = None
        if guard:
            g = {"raw_role": guard.get("raw_role"), "title": guard.get("title")}
        self._call({"cmd": "act", "app": app, "path": list(path), "action": action, "arg": arg, "guard": g})

    def activate(self, app):
        self._call({"cmd": "activate", "app": app})

    def send_keys(self, app, text):
        self._call({"cmd": "keys", "app": app, "text": text})

    def send_combo(self, app, combo):
        mods, key = parse_combo(combo)
        code = _KEYCODES.get(key)
        if code is None and len(key) != 1:
            raise UictlError("unknown key %r (single character or one of %s)" % (key, ", ".join(sorted(_KEYCODES))))
        self._call({"cmd": "combo", "app": app, "using": [_USING[m] for m in mods],
                    "code": code, "char": key if code is None else None})
