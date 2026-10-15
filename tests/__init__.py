"""Test package initialization.

Some test runners alter the import path to the directory containing this file.
Ensure the repository root is available so imports such as ``app.validator``
resolve reliably.
"""

import os
import sys

# Put the project root first if it is not already present.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
