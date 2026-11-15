"""Repository-root pytest bootstrap.

This file is loaded by pytest before any test module or package ``__init__`` is imported. It works around an
environment defect: Twisted 26.10.0 on Windows with CPython 3.12 raises
``NameError: name 'PureWindowsPath' is not defined`` from ``twisted.python.filepath`` whenever ``FilePath.child()``
is used. In that Twisted version, ``PureWindowsPath`` is imported only when ``sys.version_info <= (3, 12)`` but used
when ``sys.version_info < (3, 13)``, so on 3.12 the name is missing.

Two patches are applied, both no-ops on other platforms / Python versions and when the bug is absent:

1. In-process, immediately, before any Twisted module is imported by the tests.
2. For the ``scrapyd.runner`` subprocesses spawned by the webservice and launcher tests, by putting the
   ``tests/_compat`` directory (which contains a ``sitecustomize.py``) on ``PYTHONPATH``; child processes inherit it
   and CPython imports ``sitecustomize`` at startup, patching them before Twisted's filepath module is loaded.
"""

import os
import sys
from pathlib import Path

if sys.platform == "win32" and sys.version_info[:2] == (3, 12):
    from pathlib import PureWindowsPath

    from twisted.python import filepath

    if not hasattr(filepath, "PureWindowsPath"):
        filepath.PureWindowsPath = PureWindowsPath

    _compat_entry = str(Path(__file__).parent / "tests" / "_compat")
    _existing_pythonpath = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = (
        _compat_entry if not _existing_pythonpath else os.pathsep.join([_compat_entry, _existing_pythonpath])
    )
