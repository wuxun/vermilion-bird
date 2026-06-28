"""Common pytest fixtures for ember packages."""

import pytest
import sys
import os

# Ensure ember packages are on path
_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_base, "packages", "ember-core", "src"))
sys.path.insert(0, os.path.join(_base, "packages", "ember-agent", "src"))
sys.path.insert(0, os.path.join(_base, "src"))
