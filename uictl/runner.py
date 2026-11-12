"""Step runner: select -> act -> verify, with retries/backoff. Backend-agnostic.

Action file (JSON):
{
  "name": "export-report", "app": "MyApp",
  "params": {"path": {"required": true}, "fmt": {"default": "csv"}},
  "steps": [
    {"op": "click", "select": {"role": "button", "title": "Export"},
     "expect": [{"exists": {"role": "window", "title": "Save"}}], "retries": 2, "timeout": 5},
    {"op": "type", "select": {"role": "textfield", "within": {"role": "window", "title": "Save"}}, "text": "{path}"},
    {"op": "key", "combo": "return", "expect": [{"gone": {"role": "window", "title": "Save"}}]}
  ]
}
ops: click | type | keys | key | focus | activate | get | wait | assert | sleep
expect/pre conditions: {"exists": sel} {"gone": sel} {"enabled": sel}
                       {"value": {"select": sel, "equals"|"contains": str}}
"""
from __future__ import annotations
import time
from .model import UictlError, NotFound, Ambiguous, find_one, find_all, describe

BACKOFF = (1.0, 2.0, 5.0)
POLL = 0.25


class StepFailed(UictlError):
    pass


def subst(obj, params):
    if isinstance(obj, str):
        try:
            return obj.format_map(params)
        except KeyError as e:
            raise UictlError("unknown parameter %s" % e)
    if isinstance(obj, dict):
        return {k: subst(v, params) for k, v in obj.items()}
    if isinstance(obj, list):
        return [subst(v, params) for v in obj]
    return obj


def resolve_params(spec, given):
    out = {}
    for name, d in (spec or {}).items():
        if name in given:
            out[name] = given[name]
        elif "default" in d:
            out[name] = d["default"]
        elif d.get("required"):
            raise UictlError("missing required parameter %r" % name)
    for k, v in given.items():
        out.setdefault(k, v)
    return out


class Runner:
    def __init__(self, backend, sleep=time.sleep, clock=time.monotonic, dry_run=False, depth=8, log=None):
        self.b, self.sleep, self.clock, self.dry_run, self.depth = backend, sleep, clock, dry_run, depth
        self.log = log or (lambda msg: None)

    # -- conditions -------------------------------------------------------
    def check(self, app, cond):
        tree = self.b.snapshot(app, self.depth)
        if "exists" in cond:
            return bool(find_all(tree, cond["exists"]))
        if "gone" in cond:
            return not find_all(tree, cond["gone"])
        if "enabled" in cond:
            hits = find_all(tree, cond["enabled"])
            return bool(hits) and bool(hits[0][1].get("enabled"))
        if "value" in cond:
            v = cond["value"]
            hits = find_all(tree, v["select"])
            if not hits:
                return False
            val = hits[0][1].get("value") or ""
            if "equals" in v:
                return val == v["equals"]
            if "contains" in v:
                return v["contains"] in val
        raise UictlError("unknown condition %r" % (cond,))

    def wait_for(self, app, conds, timeout):
        end = self.clock() + timeout
        while True:
            pending = [c for c in conds if not self.check(app, c)]
            if not pending:
                return
            if self.clock() >= end:
                raise StepFailed("timed out after %ss waiting for %r" % (timeout, pending[0]))
            self.sleep(POLL)

    # -- ops --------------------------------------------------------------
    def locate(self, app, sel):
        tree = self.b.snapshot(app, self.depth)
        path, node = find_one(tree, sel)
        return path, node

    def _act_on(self, app, sel, action, arg=None):
        try:
            path, node = self.locate(app, sel)
        except NotFound:
            if self.dry_run:  # may depend on UI state an earlier (skipped) step would create
                self.log("  %s -> unresolved in dry-run (not on screen yet)" % action)
                return {"unresolved": True, "dry_run": True}
            raise
        self.log("  %s -> %s @%s" % (action, describe(node), path))
        if self.dry_run:
            return {"element": describe(node), "path": path, "dry_run": True}
        self.b.act(app, path, action, arg, guard={"raw_role": node.get("raw_role"), "title": node.get("title") or ""})
        return {"element": describe(node), "path": path}

    def do_op(self, app, step, variables):
        op = step["op"]
        if op in ("click", "focus"):
            return self._act_on(app, step["select"], op)
        if op == "type":
            return self._act_on(app, step["select"], "set_value", step["text"])
        if op == "get":
            path, node = self.locate(app, step["select"])
            variables[step.get("as", "value")] = node.get("value") if node.get("value") is not None else node.get("title")
            return {"value": variables[step.get("as", "value")]}
        if op in ("wait", "assert"):
            return {}
        if op == "sleep":
            if not self.dry_run:
                self.sleep(float(step.get("seconds", 1)))
            return {}
        if self.dry_run:
            return {"dry_run": True}
        if op == "activate":
            self.b.activate(app)
        elif op == "keys":
            self.b.send_keys(app, step["text"])
        elif op == "key":
            self.b.send_combo(app, step["combo"])
        else:
            raise UictlError("unknown op %r" % op)
        return {}

    def run_step(self, app, step, variables):
        retries = int(step.get("retries", 1))
        timeout = float(step.get("timeout", 5))
        conds = list(step.get("expect", []))
        if step["op"] in ("wait", "assert") and "until" in step:
            conds += step["until"]
        last = None
        for attempt in range(retries + 1):
            try:
                if step.get("pre"):
                    self.wait_for(app, step["pre"], timeout)
                out = self.do_op(app, step, variables)
                if conds and not self.dry_run:
                    # assert fails immediately (timeout 0); everything else polls
                    self.wait_for(app, conds, 0 if step["op"] == "assert" else timeout)
                return {"ok": True, "attempts": attempt + 1, **out}
            except (NotFound, Ambiguous, StepFailed) as e:
                last = e
            except UictlError as e:
                last = e
            if attempt < retries:
                self.log("  retry %d after: %s" % (attempt + 1, last))
                self.sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)])
        raise StepFailed(str(last))

    def run(self, action, given=None):
        params = resolve_params(action.get("params"), given or {})
        app = action.get("app") or (given or {}).get("app")
        if not app:
            raise UictlError("action has no 'app'")
        variables = dict(params)
        results = []
        for i, raw in enumerate(action["steps"]):
            step = subst(raw, variables)
            self.log("[%d/%d] %s" % (i + 1, len(action["steps"]), step.get("name") or step["op"]))
            t0 = self.clock()
            try:
                r = self.run_step(app, step, variables)
            except StepFailed as e:
                results.append({"step": i, "op": step["op"], "ok": False, "error": str(e)})
                return {"ok": False, "failed_step": i, "error": str(e), "steps": results, "vars": variables}
            r.update(step=i, op=step["op"], ms=int((self.clock() - t0) * 1000))
            results.append(r)
        return {"ok": True, "steps": results, "vars": variables, "dry_run": self.dry_run}
