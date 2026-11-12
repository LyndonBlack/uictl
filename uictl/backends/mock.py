"""In-memory backend for tests and for trying the CLI on any OS.

Tree JSON may carry behaviours on nodes:
  "on_click": {"append_root": <node>, "remove_root_title": "Save", "set_value": {"path": [..], "value": ".."}}
"""
from __future__ import annotations
import copy
import json
from .base import Backend
from ..model import UictlError, norm_role, node_at


def _prep(n):
    n.setdefault("raw_role", n.get("role"))
    n["role"] = norm_role(n.get("role"))
    n.setdefault("enabled", True)
    n.setdefault("children", [])
    for c in n["children"]:
        _prep(c)
    return n


class MockBackend(Backend):
    name = "mock"

    def __init__(self, tree=None, tree_file=None, **_):
        if tree_file:
            with open(tree_file) as f:
                tree = json.load(f)
        self.apps = {}
        if tree:
            # accept a single app tree or {"apps": {name: tree}}
            if "apps" in tree:
                for k, v in tree["apps"].items():
                    self.apps[k] = _prep(v)
            else:
                self.apps[tree.get("title", "MockApp")] = _prep(tree)
        self.log = []

    def list_apps(self):
        return sorted(self.apps)

    def _app(self, app):
        if app not in self.apps:
            raise UictlError("process not running: %s" % app)
        return self.apps[app]

    def snapshot(self, app, depth=8):
        return copy.deepcopy(self._app(app))

    def act(self, app, path, action, arg=None, guard=None):
        root = self._app(app)
        try:
            node = node_at(root, path)
        except (IndexError, KeyError):
            raise UictlError("path %s no longer exists" % (path,))
        if guard:
            if (guard.get("raw_role") and node.get("raw_role") != guard["raw_role"]) or \
               (guard.get("title") is not None and (node.get("title") or "") != (guard["title"] or "")):
                raise UictlError("element at %s changed (guard mismatch)" % (path,))
        if not node.get("enabled", True):
            raise UictlError("element is disabled")
        self.log.append((action, list(path), arg))
        if action == "set_value":
            node["value"] = arg
        elif action == "click":
            oc = node.get("on_click") or {}
            if "append_root" in oc:
                root["children"].append(_prep(copy.deepcopy(oc["append_root"])))
            if "remove_root_title" in oc:
                root["children"] = [c for c in root["children"] if c.get("title") != oc["remove_root_title"]]
            if "set_value" in oc:
                node_at(root, oc["set_value"]["path"])["value"] = oc["set_value"]["value"]

    def activate(self, app):
        self._app(app)
        self.log.append(("activate", [], app))

    def send_keys(self, app, text):
        self._app(app)
        self.log.append(("keys", [], text))

    def send_combo(self, app, combo):
        self._app(app)
        self.log.append(("combo", [], combo))
