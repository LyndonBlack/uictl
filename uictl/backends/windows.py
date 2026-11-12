"""Windows backend: .NET UI Automation driven through PowerShell. No third-party code, no network.

Uses System.Windows.Automation (ships with Windows PowerShell 5.1 / .NET Framework).
Limits: needs Add-Type permitted (not Constrained Language Mode); cannot drive elevated
apps from a non-elevated shell; SendKeys is used for typing. UNTESTED as of v0.1.0.
"""
from __future__ import annotations
import json
import os
import subprocess
import tempfile
from .base import Backend, parse_combo
from ..model import UictlError, norm_role

PS = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms
$req = $env:UICTL_REQ | ConvertFrom-Json
$AE = [System.Windows.Automation.AutomationElement]
$walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
function Out-Json($o) { [Console]::Out.Write(($o | ConvertTo-Json -Depth 100 -Compress)) }
function Fail($m) { Out-Json @{ ok = $false; error = "$m" }; exit 0 }
function Kids($el) {
  $l = New-Object System.Collections.ArrayList
  $c = $walker.GetFirstChild($el)
  while ($c -ne $null) { [void]$l.Add($c); $c = $walker.GetNextSibling($c) }
  return ,$l
}
function AppWindows($app) {
  $pids = @(Get-Process -Name $app -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
  if ($pids.Count -eq 0) { Fail "process not running: $app" }
  $l = New-Object System.Collections.ArrayList
  foreach ($w in (Kids $AE::RootElement)) { if ($pids -contains $w.Current.ProcessId) { [void]$l.Add($w) } }
  return ,$l
}
function Val($el) {
  try { $p = $el.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern); return $p.Current.Value } catch { return $null }
}
function Node($el, $depth) {
  $r = $el.Current.BoundingRectangle
  $b = $null; if (-not [double]::IsInfinity($r.X)) { $b = @([int]$r.X, [int]$r.Y, [int]$r.Width, [int]$r.Height) }
  $n = [ordered]@{ raw_role = $el.Current.ControlType.ProgrammaticName; title = $el.Current.Name; value = (Val $el);
    id = $el.Current.AutomationId; enabled = $el.Current.IsEnabled; bounds = $b; children = (New-Object System.Collections.ArrayList) }
  if ($depth -lt $req.depth) { foreach ($k in (Kids $el)) { [void]$n.children.Add((Node $k ($depth + 1))) } }
  return $n
}
switch ($req.cmd) {
  'apps' {
    $names = Get-Process | Where-Object { $_.MainWindowHandle -ne 0 } | ForEach-Object { $_.ProcessName } | Sort-Object -Unique
    Out-Json @{ ok = $true; apps = @($names) }
  }
  'snapshot' {
    $root = [ordered]@{ raw_role = 'ControlType.Application'; title = $req.app; value = $null; id = $null; enabled = $true; bounds = $null; children = (New-Object System.Collections.ArrayList) }
    foreach ($w in (AppWindows $req.app)) { [void]$root.children.Add((Node $w 1)) }
    Out-Json @{ ok = $true; tree = $root }
  }
  'activate' { $w = (AppWindows $req.app)[0]; if ($w -eq $null) { Fail 'no window' }; $w.SetFocus(); Out-Json @{ ok = $true } }
  'keys' {
    $w = (AppWindows $req.app)[0]; $w.SetFocus(); Start-Sleep -Milliseconds 150
    [System.Windows.Forms.SendKeys]::SendWait($req.text); Out-Json @{ ok = $true }
  }
  'combo' {
    $w = (AppWindows $req.app)[0]; $w.SetFocus(); Start-Sleep -Milliseconds 150
    [System.Windows.Forms.SendKeys]::SendWait($req.sendkeys); Out-Json @{ ok = $true }
  }
  'act' {
    $el = $null; $kids = AppWindows $req.app
    foreach ($i in @($req.path)) {
      if ($i -ge $kids.Count) { Fail 'path no longer exists' }
      $el = $kids[$i]; $kids = Kids $el
    }
    if ($el -eq $null) { Fail 'empty path' }
    if ($req.guard) {
      if (($req.guard.raw_role -and $el.Current.ControlType.ProgrammaticName -ne $req.guard.raw_role) -or
          ($req.guard.title -ne $null -and $el.Current.Name -ne $req.guard.title)) { Fail 'element changed (guard mismatch)' }
    }
    if (-not $el.Current.IsEnabled) { Fail 'element is disabled' }
    switch ($req.action) {
      'click' {
        $done = $false
        foreach ($pat in @([System.Windows.Automation.InvokePattern], [System.Windows.Automation.TogglePattern], [System.Windows.Automation.SelectionItemPattern], [System.Windows.Automation.ExpandCollapsePattern])) {
          $o = $null
          if ($el.TryGetCurrentPattern($pat::Pattern, [ref]$o)) {
            switch ($pat.Name) {
              'InvokePattern' { $o.Invoke() } 'TogglePattern' { $o.Toggle() }
              'SelectionItemPattern' { $o.Select() } 'ExpandCollapsePattern' { $o.Expand() }
            }
            $done = $true; break
          }
        }
        if (-not $done) { Fail 'no invokable pattern on element' }
      }
      'set_value' { $el.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue([string]$req.arg) }
      'focus' { $el.SetFocus() }
      default { Fail "unknown action $($req.action)" }
    }
    Out-Json @{ ok = $true }
  }
  default { Fail "unknown cmd $($req.cmd)" }
}
"""

_NAMED = {"return": "{ENTER}", "enter": "{ENTER}", "tab": "{TAB}", "escape": "{ESC}", "esc": "{ESC}",
          "delete": "{DEL}", "backspace": "{BS}", "left": "{LEFT}", "right": "{RIGHT}", "up": "{UP}",
          "down": "{DOWN}", "home": "{HOME}", "end": "{END}", "pageup": "{PGUP}", "pagedown": "{PGDN}",
          "space": " "}
_SPECIAL = set("+^%~(){}[]")


def sendkeys_escape(text):
    return "".join("{%s}" % c if c in _SPECIAL else c for c in text)


class WindowsBackend(Backend):
    name = "windows"

    def __init__(self, runner=None, timeout=60, **_):
        self._runner = runner or self._powershell
        self.timeout = timeout

    def _powershell(self, req):
        fd, path = tempfile.mkstemp(suffix=".ps1")
        try:
            with os.fdopen(fd, "w", encoding="utf-8-sig") as f:
                f.write(PS)
            env = dict(os.environ, UICTL_REQ=json.dumps(req))
            exe = "powershell"
            try:
                p = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", path],
                                   capture_output=True, text=True, timeout=self.timeout, env=env)
            except FileNotFoundError:
                raise UictlError("powershell not found: this backend only runs on Windows")
            except subprocess.TimeoutExpired:
                raise UictlError("powershell timed out after %ss" % self.timeout)
        finally:
            os.unlink(path)
        if p.returncode != 0:
            raise UictlError("powershell failed: %s" % (p.stderr.strip() or p.stdout.strip()))
        return p.stdout

    def _call(self, req):
        raw = self._runner(req)
        try:
            data = json.loads(raw)
        except ValueError:
            raise UictlError("unparseable powershell output: %r" % raw[:200])
        if not data.get("ok"):
            raise UictlError(data.get("error", "unknown error"))
        return data

    def is_available(self):
        import sys
        return sys.platform == "win32"

    def list_apps(self):
        return list(self._call({"cmd": "apps"})["apps"])

    def snapshot(self, app, depth=8):
        tree = self._call({"cmd": "snapshot", "app": app, "depth": depth})["tree"]

        def fix(n):
            n["role"] = norm_role(n.get("raw_role"))
            if n.get("children") is None:
                n["children"] = []
            for c in n["children"]:
                fix(c)
        fix(tree)
        return tree

    def act(self, app, path, action, arg=None, guard=None):
        g = {"raw_role": guard.get("raw_role"), "title": guard.get("title")} if guard else None
        self._call({"cmd": "act", "app": app, "path": list(path), "action": action, "arg": arg, "guard": g})

    def activate(self, app):
        self._call({"cmd": "activate", "app": app})

    def send_keys(self, app, text):
        self._call({"cmd": "keys", "app": app, "text": sendkeys_escape(text)})

    def send_combo(self, app, combo):
        mods, key = parse_combo(combo)
        prefix = "".join({"ctrl": "^", "alt": "%", "shift": "+", "cmd": "^"}[m] for m in mods)
        k = _NAMED.get(key, sendkeys_escape(key) if len(key) == 1 else None)
        if k is None:
            raise UictlError("unknown key %r" % key)
        self._call({"cmd": "combo", "app": app, "sendkeys": prefix + k})
