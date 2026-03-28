class DistributionNotFound(Exception):
    pass


def get_distribution(name):
    raise DistributionNotFound(name)


def iter_entry_points(group=None, name=None):
    return iter(())


def declare_namespace(name):
    pass
