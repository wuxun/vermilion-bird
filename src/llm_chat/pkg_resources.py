"""pkg_resources shim for Python 3.14 compatibility.

Python 3.14 removed pkg_resources module. This shim provides
minimal compatibility for legacy packages that depend on it.
"""

import sys


# Create the exception class that APScheduler expects
class DistributionNotFound(Exception):
    """Raised when a requested distribution is not found."""

    pass


# Create a minimal Distribution object
class _Distribution:
    def __init__(self, name=None, version=None):
        self.name = name
        self.version = version

    def __repr__(self):
        return f"{self.name} {self.version}"


# The get_distribution function that APScheduler calls
def get_distribution(dist=None):
    """Return a distribution object or raise DistributionNotFoundError."""
    if dist and dist.lower() != "apscheduler":
        raise DistributionNotFound(f"Distribution {dist} not found")
    return _Distribution(name="apscheduler", version="3.9.1")


# Register the module with sys.modules before any imports happen
sys.modules["pkg_resources"] = sys.modules[__name__]
sys.modules["pkg_resources._distributions"] = sys.modules[__name__]

# Make everything available at module level for APScheduler to import
__all__ = ["get_distribution", "DistributionNotFound"]
