class DistributionNotFound(Exception):
    pass


def get_distribution(name):
    # Minimal stub to satisfy APScheduler import in environments without
    # setuptools/pkg_resources available. APScheduler expects to catch
    # DistributionNotFound; raise it to trigger fallback behavior.
    raise DistributionNotFound(name)


def iter_entry_points(group=None, name=None):
    # Return an empty iterator to simulate absence of extra plugins
    return iter(())
