import json, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from uictl.model import find_all, find_one, NotFound, Ambiguous, norm_role, parse_selector
from uictl.backends import MockBackend, parse_combo
from uictl.backends.macos import MacOSBackend
from uictl.backends.windows import WindowsBackend, sendkeys_escape
from uictl.runner import Runner, StepFailed, resolve_params
from uictl.model import UictlError
from uictl import cli

EX = os.path.join(os.path.dirname(__file__), "..", "examples")


class FakeTime:
    def __init__(self): self.t = 0.0; self.sleeps = []
    def sleep(self, s): self.sleeps.append(s); self.t += s
    def clock(self): return self.t


def mock():
    return MockBackend(tree_file=os.path.join(EX, "mock_app.json"))


def runner(b, **kw):
    ft = FakeTime()
    return Runner(b, sleep=ft.sleep, clock=ft.clock, **kw), ft


class SelectorTests(unittest.TestCase):
    def test_role_normalisation(self):
        self.assertEqual(norm_role("AXButton"), "button")
        self.assertEqual(norm_role("ControlType.Button"), "button")
        self.assertEqual(norm_role("AXStaticText"), "text")
        self.assertEqual(norm_role("ControlType.Edit"), "textfield")

    def test_find_and_ambiguity(self):
        tree = mock().snapshot("DemoApp")
        p, n = find_one(tree, {"role": "button", "title": "Export"})
        self.assertEqual(n["title"], "Export")
        with self.assertRaises(NotFound):
            find_one(tree, {"title": "Nope"})
        with self.assertRaises(Ambiguous):
            find_one(tree, {"role": "text"} if False else {"enabled": True})
        self.assertEqual(find_one(tree, {"enabled": True, "index": 0})[1]["title"], "Reports")

    def test_within(self):
        b = mock(); r, _ = runner(b)
        r.run({"app": "DemoApp", "steps": [{"op": "click", "select": {"title": "Export"}}]})
        tree = b.snapshot("DemoApp")
        hits = find_all(tree, {"role": "button", "title": "OK", "within": {"role": "window", "title": "Save"}})
        self.assertEqual(len(hits), 1)

    def test_parse_selector(self):
        self.assertEqual(parse_selector("role=button,title=Export,index=1"), {"role": "button", "title": "Export", "index": 1})
        self.assertEqual(parse_selector('{"role":"x"}'), {"role": "x"})


class RunnerTests(unittest.TestCase):
    def action(self):
        with open(os.path.join(EX, "export.action.json")) as f:
            return json.load(f)

    def test_full_export_flow(self):
        b = mock(); r, _ = runner(b)
        res = r.run(self.action(), {"path": "/tmp/out.csv"})
        self.assertTrue(res["ok"], res)
        self.assertIn(("set_value", [1, 0], "/tmp/out.csv"), b.log)

    def test_missing_param(self):
        r, _ = runner(mock())
        with self.assertRaises(UictlError):
            r.run(self.action(), {})

    def test_dry_run_does_not_act(self):
        b = mock(); r, _ = runner(b, dry_run=True)
        res = r.run(self.action(), {"path": "x"})
        self.assertTrue(res["ok"]); self.assertEqual(b.log, [])

    def test_failure_retries_with_backoff(self):
        b = mock(); r, ft = runner(b)
        act = {"app": "DemoApp", "steps": [{"op": "click", "select": {"role": "button", "title": "Missing"}, "retries": 2}]}
        res = r.run(act)
        self.assertFalse(res["ok"]); self.assertEqual(ft.sleeps, [1.0, 2.0])

    def test_expect_timeout_fails(self):
        b = mock(); r, ft = runner(b)
        act = {"app": "DemoApp", "steps": [{"op": "click", "select": {"role": "textfield", "title": "Name"},
               "expect": [{"exists": {"title": "Never"}}], "timeout": 1, "retries": 0}]}
        res = r.run(act)
        self.assertFalse(res["ok"]); self.assertIn("timed out", res["error"])

    def test_get_captures_variable_for_later_steps(self):
        b = mock(); r, _ = runner(b)
        act = {"app": "DemoApp", "steps": [
            {"op": "get", "select": {"role": "text", "title": "Status"}, "as": "st"},
            {"op": "type", "select": {"role": "textfield", "title": "Name"}, "text": "was-{st}"}]}
        res = r.run(act)
        self.assertTrue(res["ok"]); self.assertIn(("set_value", [0, 0], "was-Idle"), b.log)

    def test_guard_catches_tree_change(self):
        b = mock()
        with self.assertRaises(UictlError):
            b.act("DemoApp", [0, 1], "click", guard={"raw_role": "AXButton", "title": "Different"})

    def test_assert_fails_immediately(self):
        r, ft = runner(mock())
        res = r.run({"app": "DemoApp", "steps": [{"op": "assert", "until": [{"exists": {"title": "Nope"}}], "retries": 0}]})
        self.assertFalse(res["ok"]); self.assertEqual(ft.sleeps, [])


class BackendWireTests(unittest.TestCase):
    def test_macos_requests_and_parse(self):
        seen = []
        def fake(req):
            seen.append(req)
            if req["cmd"] == "snapshot":
                return json.dumps({"ok": True, "tree": {"raw_role": "AXApplication", "title": "X", "children": [
                    {"raw_role": "AXButton", "title": "Go", "children": []}]}})
            return json.dumps({"ok": True})
        b = MacOSBackend(runner=fake)
        t = b.snapshot("X")
        self.assertEqual(t["children"][0]["role"], "button")
        b.act("X", [0], "click", guard={"raw_role": "AXButton", "title": "Go"})
        b.send_combo("X", "cmd+shift+s"); b.send_combo("X", "return")
        self.assertEqual(seen[2]["using"], ["command down", "shift down"]); self.assertEqual(seen[2]["char"], "s")
        self.assertEqual(seen[3]["code"], 36)
        self.assertEqual(seen[1]["guard"], {"raw_role": "AXButton", "title": "Go"})

    def test_macos_error_surfaces(self):
        b = MacOSBackend(runner=lambda r: json.dumps({"ok": False, "error": "process not running: X"}))
        with self.assertRaises(UictlError): b.snapshot("X")

    def test_windows_wire(self):
        seen = []
        def fake(req):
            seen.append(req)
            if req["cmd"] == "snapshot":
                return json.dumps({"ok": True, "tree": {"raw_role": "ControlType.Application", "title": "X", "children": [
                    {"raw_role": "ControlType.Button", "title": "Go", "children": None}]}})
            return json.dumps({"ok": True})
        b = WindowsBackend(runner=fake)
        self.assertEqual(b.snapshot("X")["children"][0]["role"], "button")
        b.send_combo("X", "ctrl+s"); b.send_keys("X", "a+b")
        self.assertEqual(seen[1]["sendkeys"], "^s"); self.assertEqual(seen[2]["text"], "a{+}b")
        self.assertEqual(sendkeys_escape("{x}"), "{{}x{}}")

    def test_combo_parse(self):
        self.assertEqual(parse_combo("cmd+shift+s"), (["cmd", "shift"], "s"))
        with self.assertRaises(ValueError): parse_combo("bogus+s")


class CliTests(unittest.TestCase):
    def test_cli_run_json(self):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["--backend", "mock", "--mock-tree", os.path.join(EX, "mock_app.json"), "--json",
                           "run", os.path.join(EX, "export.action.json"), "-p", "path=/tmp/a"])
        self.assertEqual(rc, 0); self.assertTrue(json.loads(buf.getvalue())["ok"])

    def test_cli_inspect_and_error(self):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["--backend", "mock", "--mock-tree", os.path.join(EX, "mock_app.json"), "inspect", "DemoApp", "--flat"])
        self.assertEqual(rc, 0); self.assertIn("button 'Export'", buf.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["--backend", "mock", "--mock-tree", os.path.join(EX, "mock_app.json"), "inspect", "Nope"]), 1)


if __name__ == "__main__":
    unittest.main()
