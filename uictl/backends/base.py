"""Backend contract. Each platform implements ~6 primitives; everything else is shared."""
from __future__ import annotations
from abc import ABC, abstractmethod


class Backend(ABC):
    name = "base"

    @abstractmethod
    def list_apps(self):
        """-> list[str] of automatable app/process names."""

    @abstractmethod
    def snapshot(self, app, depth=8):
        """-> tree dict (see model.py). Root is a synthetic application node."""

    @abstractmethod
    def act(self, app, path, action, arg=None, guard=None):
        """Perform action on the element at path. action in:
        click | set_value | focus.
        guard={'raw_role','title'}: the backend must re-check the element at
        path still matches before acting and raise if not (tree changed under us)."""

    @abstractmethod
    def activate(self, app):
        """Bring app to the foreground."""

    @abstractmethod
    def send_keys(self, app, text):
        """Type literal text into the focused control."""

    @abstractmethod
    def send_combo(self, app, combo):
        """Press a key combo such as 'cmd+s', 'ctrl+shift+n', 'return'."""

    def is_available(self):
        return True


MODS = {"cmd": "cmd", "command": "cmd", "win": "cmd", "super": "cmd", "ctrl": "ctrl", "control": "ctrl",
        "alt": "alt", "opt": "alt", "option": "alt", "shift": "shift"}


def parse_combo(combo):
    """'cmd+shift+s' -> (['cmd','shift'], 's'). Raises ValueError on empty."""
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not parts:
        raise ValueError("empty key combo")
    mods = [MODS[p] for p in parts[:-1] if p in MODS]
    if len(mods) != len(parts) - 1:
        raise ValueError("unknown modifier in %r" % combo)
    return mods, parts[-1]
