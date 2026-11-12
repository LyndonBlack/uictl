"""uictl command line. stdlib argparse only. Every command supports --json."""
from __future__ import annotations
import argparse
import json
import shlex
import sys
from .backends import get_backend
from .model import UictlError, parse_selector, find_all, find_one, describe, walk
from .runner import Runner


def _emit(args, data, human):
    if args.json:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(human if isinstance(human, str) else "\n".join(human))


def _tree_lines(tree, flat=False):
    out = []
    for path, n in walk(tree):
        if not path and not flat:
            out.append("%s %r" % (n.get("role"), n.get("title")))
            continue
        extra = ""
        if n.get("value") not in (None, ""):
            extra += " value=%r" % n["value"]
        if n.get("id"):
            extra += " id=%s" % n["id"]
        if n.get("enabled") is False:
            extra += " (disabled)"
        label = "%s %r%s" % (n.get("role"), n.get("title") or "", extra)
        out.append(("%-16s %s" % (path, label)) if flat else "%s%s" % ("  " * len(path), label))
    return out


def build_parser():
    p = argparse.ArgumentParser(prog="uictl", description="Offline UI automation: inspect, find, click, type, run action files.")
    p.add_argument("--backend", default="auto", choices=["auto", "macos", "windows", "mock"])
    p.add_argument("--mock-tree", help="tree JSON for the mock backend")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--dry-run", action="store_true", help="resolve selectors, do not act")
    p.add_argument("--depth", type=int, default=8)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("backends", help="show available backends")
    sub.add_parser("apps", help="list automatable apps")
    s = sub.add_parser("inspect", help="dump an app's UI tree (do this first)")
    s.add_argument("app"); s.add_argument("--flat", action="store_true"); s.add_argument("--save", help="write full tree JSON here")
    for name, hlp in (("find", "list elements matching a selector"), ("click", "click/press an element"),
                      ("get", "read an element's value/title"), ("focus", "focus an element")):
        s = sub.add_parser(name, help=hlp); s.add_argument("app"); s.add_argument("select")
    s = sub.add_parser("type", help="set an element's value"); s.add_argument("app"); s.add_argument("select"); s.add_argument("text")
    s = sub.add_parser("keys", help="type literal text into the focused control"); s.add_argument("app"); s.add_argument("text")
    s = sub.add_parser("key", help="press a key combo, e.g. cmd+s"); s.add_argument("app"); s.add_argument("combo")
    s = sub.add_parser("wait", help="wait for an element to appear (or --gone)")
    s.add_argument("app"); s.add_argument("select"); s.add_argument("--gone", action="store_true"); s.add_argument("--timeout", type=float, default=10)
    s = sub.add_parser("run", help="run an action file")
    s.add_argument("file"); s.add_argument("--app"); s.add_argument("--param", "-p", action="append", default=[], metavar="K=V")
    sub.add_parser("repl", help="interactive shell")
    return p


def make_runner(args, backend):
    return Runner(backend, dry_run=args.dry_run, depth=args.depth,
                  log=(lambda m: print(m, file=sys.stderr)) if args.verbose else None)


def dispatch(args, backend):
    c = args.cmd
    if c == "backends":
        data = {"selected": backend.name, "available": backend.is_available()}
        return _emit(args, data, "%s (available=%s)" % (backend.name, backend.is_available()))
    if c == "apps":
        apps = backend.list_apps()
        return _emit(args, {"apps": apps}, apps or "(none)")
    if c == "inspect":
        tree = backend.snapshot(args.app, args.depth)
        if args.save:
            with open(args.save, "w") as f:
                json.dump(tree, f, indent=2)
        return _emit(args, tree, _tree_lines(tree, args.flat))
    if c == "find":
        hits = find_all(backend.snapshot(args.app, args.depth), parse_selector(args.select))
        return _emit(args, [{"path": p, **{k: v for k, v in n.items() if k != "children"}} for p, n in hits],
                     ["%-16s %s" % (p, describe(n)) for p, n in hits] or "(no matches)")
    if c in ("click", "focus", "type", "get"):
        step = {"op": c, "select": parse_selector(args.select)}
        if c == "type":
            step["text"] = args.text
        r = make_runner(args, backend)
        out = r.run_step(args.app, step, {})
        return _emit(args, out, "ok: %s" % (out.get("element") or out.get("value")))
    if c in ("keys", "key"):
        step = {"op": c, "text": getattr(args, "text", None), "combo": getattr(args, "combo", None)}
        out = make_runner(args, backend).run_step(args.app, step, {})
        return _emit(args, out, "ok")
    if c == "wait":
        sel = parse_selector(args.select)
        step = {"op": "wait", "until": [{"gone" if args.gone else "exists": sel}], "timeout": args.timeout, "retries": 0}
        out = make_runner(args, backend).run_step(args.app, step, {})
        return _emit(args, out, "ok")
    if c == "run":
        with open(args.file) as f:
            action = json.load(f)
        params = {}
        for kv in args.param:
            k, _, v = kv.partition("=")
            params[k] = v
        if args.app:
            action["app"] = args.app
        out = make_runner(args, backend).run(action, params)
        _emit(args, out, ["step %d %s: %s" % (s["step"], s["op"], "ok" if s["ok"] else s.get("error")) for s in out["steps"]]
              + ["RESULT: " + ("ok" if out["ok"] else "FAILED - " + out["error"])])
        return 0 if out["ok"] else 1
    raise UictlError("unknown command %r" % c)


def repl(args, backend):
    p = build_parser()
    print("uictl repl (%s). 'help' for commands, 'quit' to exit." % backend.name)
    while True:
        try:
            line = input("uictl> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(); return 0
        if not line:
            continue
        if line in ("quit", "exit", "q"):
            return 0
        if line == "help":
            p.print_help(); continue
        try:
            sub_args = p.parse_args(["--backend", args.backend] + (["--json"] if args.json else []) + shlex.split(line))
            if sub_args.cmd in (None, "repl"):
                continue
            dispatch(sub_args, backend)
        except SystemExit:
            pass
        except UictlError as e:
            print("error: %s" % e)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        backend = get_backend(args.backend, tree_file=args.mock_tree) if args.backend == "mock" else get_backend(args.backend)
        if args.cmd in (None, "repl"):
            return repl(args, backend)
        rc = dispatch(args, backend)
        return rc or 0
    except UictlError as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            print("error: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
