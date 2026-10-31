"Utility functions that support lazy iteration."


def flatten(iterable):
    """
    Flattens a sequence of iterables (potentially of iterables themselves)
    into a single iterable.

    :param iterable: The iterable of iterables (perhaps of other iterables, and so on)
    :return: A flattened iterable
    """
    for element in iterable:
        if isinstance(element, (list, tuple, set)) and not isinstance(element, str):
            yield from flatten(element)
        else:
            yield element
