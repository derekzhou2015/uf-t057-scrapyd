"""Auto-imported compatibility shim, made importable via ``PYTHONPATH`` by the repository-root ``conftest.py``.

CPython imports any ``sitecustomize`` module found on ``sys.path`` during interpreter startup, including for the
``scrapyd.runner`` subprocesses spawned by the test suite. It works around an environment defect: Twisted 26.10.0 on
Windows with CPython 3.12 raises ``NameError: name 'PureWindowsPath' is not defined`` from
``twisted.python.filepath`` whenever ``FilePath.child()`` is used, because that version imports ``PureWindowsPath``
only when ``sys.version_info <= (3, 12)`` but uses it when ``sys.version_info < (3, 13)``. On 3.12 the name is thus
missing. This is unrelated to Scrapyd and is a no-op elsewhere.
"""

import sys

if sys.platform == "win32" and sys.version_info[:2] == (3, 12):
    from pathlib import PureWindowsPath

    import twisted.python.filepath as _filepath

    if not hasattr(_filepath, "PureWindowsPath"):
        _filepath.PureWindowsPath = PureWindowsPath
