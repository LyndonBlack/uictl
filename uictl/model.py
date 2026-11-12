"""Shared types and selector matching. Trees are plain dicts so they serialise as JSON.

Node: {role, raw_role, title, value, id, enabled, bounds, children}
Path: list of child indexes from the app root (root itself = []).
"""
from __future__ import annotations
import re


class UictlError(Exception):
    pass


class NotFound(UictlError):
    pass


class Ambiguous(UictlError):
    pass


_ROLE_ALIASES = {
    "statictext": "text", "edit": "textfield", "document": "textarea",
    "popupbutton": "popup", "radiobutton": "radio", "pane": "group",
    "titlebar": "titlebar", "menubaritem": "menubaritem",
}


def norm_role(raw):
    """AXButton / ControlType.Button -> 'button' so selectors port across platforms."""
    r = (raw or "").replace("ControlType.", "")
    if r.startswith("AX"):
        r = r[2:]
    r = r.lower()
    return _ROLE_ALIASES.get(r, r)


def _eq(a, b):
    return (a or "") == (b or "")


def matches(node, sel):
    """Selector keys: role, title, title_contains, title_re, value, value_contains,
    id, enabled. 'index', 'within' and 'first' are handled by find()."""
    if "role" in sel and norm_role(node.get("raw_role") or node.get("role")) != norm_role(sel["role"]):
        return False
    if "title" in sel and not _eq(node.get("title"), sel["title"]):
        return False
    if "title_contains" in sel and sel["title_contains"].lower() not in (node.get("title") or "").lower():
        return False
    if "title_re" in sel and not re.search(sel["title_re"], node.get("title") or ""):
        return False
    if "value" in sel and not _eq(node.get("value"), sel["value"]):
        return False
    if "value_contains" in sel and sel["value_contains"] not in (node.get("value") or ""):
        return False
    if "id" in sel and not _eq(node.get("id"), sel["id"]):
        return False
    if "enabled" in sel and bool(node.get("enabled")) != bool(sel["enabled"]):
        return False
    return True


def walk(node, path=()):
    yield list(path), node
    for i, c in enumerate(node.get("children") or []):
        yield from walk(c, tuple(path) + (i,))


def node_at(tree, path):
    n = tree
    for i in path:
        n = n["children"][i]
    return n


def find_all(tree, sel):
    """All (path, node) matches, DFS order. 'within' narrows to the first match of a sub-selector."""
    base_path, base = [], tree
    if "within" in sel:
        hits = find_all(tree, sel["within"])
        if not hits:
            return []
        base_path, base = hits[0]
    crit = {k: v for k, v in sel.items() if k not in ("index", "within", "first")}
    out = []
    for p, n in walk(base, base_path):
        if p == base_path and base is tree:
            continue  # never match the synthetic app root
        if matches(n, crit):
            out.append((p, n))
    return out


def find_one(tree, sel):
    hits = find_all(tree, sel)
    if not hits:
        raise NotFound("no element matches %r" % (sel,))
    if "index" in sel:
        try:
            return hits[int(sel["index"])]
        except IndexError:
            raise NotFound("index %s out of range (%d matches) for %r" % (sel["index"], len(hits), sel))
    if len(hits) > 1 and not sel.get("first"):
        desc = "; ".join("%s %r @%s" % (n.get("role"), n.get("title"), p) for p, n in hits[:6])
        raise Ambiguous("%d elements match %r (add index/first/within): %s" % (len(hits), sel, desc))
    return hits[0]


def describe(node):
    return "%s %r" % (node.get("role"), node.get("title") or node.get("value") or node.get("id") or "")


def parse_selector(text):
    """CLI shorthand: 'role=button,title=Export' or a JSON object."""
    import json
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    sel = {}
    for part in text.split(","):
        if "=" not in part:
            raise UictlError("bad selector part %r (use key=value)" % part)
        k, v = part.split("=", 1)
        k = k.strip()
        if k == "index":
            sel[k] = int(v)
        elif k in ("enabled", "first"):
            sel[k] = v.strip().lower() in ("1", "true", "yes")
        else:
            sel[k] = v
    return sel
