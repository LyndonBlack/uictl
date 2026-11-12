from .base import Backend, parse_combo
from .mock import MockBackend


def get_backend(name="auto", **kw):
    import sys
    if name == "auto":
        name = {"darwin": "macos", "win32": "windows"}.get(sys.platform, "mock")
    if name == "macos":
        from .macos import MacOSBackend
        return MacOSBackend(**kw)
    if name == "windows":
        from .windows import WindowsBackend
        return WindowsBackend(**kw)
    if name == "mock":
        return MockBackend(**kw)
    raise ValueError("unknown backend %r" % name)
