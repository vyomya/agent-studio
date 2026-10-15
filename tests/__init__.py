"""Test package initialization.

Ensures that the repository root (which contains the ``app`` package) is on
``sys.path`` when pytest runs the tests. Some test runners alter the import
path to the directory containing the test file, causing ``import app`` to fail.
Appending the parent directory (the project root) makes the import reliable.
"""

import os
import sys

# Add the repository root to the import search path.
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.append(repo_root)

