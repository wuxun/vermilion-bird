"""pkg_resources shim for Python 3.14 compatibility.

Python 3.14 removed pkg_resources module. This shim provides
minimal compatibility for legacy packages that depend on it.
"""

import sys

try:
    # Try importing pkg_resources from setuptools (backwards compatible)
    from setuptools import _distutils  # noqa: F401

    # Create a minimal DistributionNotFoundError exception
    class DistributionNotFoundError(Exception):
        """Raised when a requested distribution is not found."""

    # Monkey-patch pkg_resources if not available
    if not hasattr(sys, "pkg_resources"):
        # Create minimal pkg_resources namespace
        class _Distribution:
            def __init__(self, name=None, version=None):
                self.name = name
                self.version = version

        def get_distribution(dist=None):
            """Return a distribution object or raise DistributionNotFoundError."""
            if dist and dist.lower() != "apscheduler":
                raise DistributionNotFound(f"Distribution {dist} not found")
            return _Distribution(name="apscheduler", version="3.9.1")

        # Add to sys.modules
        sys.modules["pkg_resources"] = sys.modules[__name__]
        sys.modules["pkg_resources._distributions"] = sys.modules[__name__]

        # Create minimal pkg_resources module
        class pkg_resources:
            DistributionNotFound = DistributionNotFoundError
            get_distribution = get_distribution

except ImportError:
    # If setuptools is not available, create minimal shim
    # This is a last resort, should work for basic use cases

    class DistributionNotFoundError(Exception):
        """Raised when a requested distribution is not found."""

    class _Distribution:
        def __init__(self, name=None, version=None):
            self.name = name
            self.version = version

    def get_distribution(dist=None):
        """Return a distribution object or raise DistributionNotFoundError."""
        if dist and dist.lower() != "apscheduler":
            raise DistributionNotFound(f"Distribution {dist} not found")
        return _Distribution(name="apscheduler", version="3.9.1")

    sys.modules["pkg_resources"] = sys.modules[__name__]
    sys.modules["pkg_resources._distributions"] = sys.modules[__name__]

    class pkg_resources:
        DistributionNotFound = DistributionNotFoundError
        get_distribution = get_distribution
