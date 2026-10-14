"""Test package initialization.

Adding an ``__init__`` file makes the ``tests`` directory a proper Python package.
It also ensures that the repository root is on ``sys.path`` when the test suite
is executed, allowing imports such as ``app.validator`` to resolve correctly.
"""

import os
import sys

# Insert the project root (the directory containing this file's parent) at the
# start of ``sys.path`` if it is not already present. This mirrors the layout the
# repository expects when running tests directly via ``pytest`` from the root.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

