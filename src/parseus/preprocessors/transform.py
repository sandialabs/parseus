"Functions to support transformation of data."

from functools import wraps
from itertools import islice


def one_to_many(dictionary_iter, transformer, **kwargs):
    """Takes an iterable of documents, and returns a lazy
    iterator for a one-to-many transformation of the documents.

    :param dictionary_iter: An iterable of dictionaries
    :param transformer: Callable that takes one document and returns
                        an iterable of zero or more documents as a result
                        of the transformation. The transformation doesn't
                        need to be deterministic, but the length of the
                        transformation must be.
    :param kwargs: Passed to the transformer callable
    :return: Iterable of transformed documents
    """

    for doc in dictionary_iter:
        yield from transformer(doc, **kwargs)


def wrap_generator_function(generator_creator: callable) -> callable:
    """Wraps a generator into a class that lets it repeat the iterable
    and defines common methods like __len__, __bool__, and __getitem__.

    :param generator_creator: A function that creates the generator to be wrapped
    :return: The resulting object
    """

    @wraps(generator_creator)
    def _callback(*args, **kwargs):
        class _TransformedIterable:
            def __init__(self):
                self._len = None  # cache the number of output documents

            def __iter__(self):
                def _new_generator():
                    i = 0
                    for item in generator_creator(*args, **kwargs):
                        yield item
                        i += 1
                    self._len = i

                return _new_generator()

            def __bool__(self):
                if self._len is not None:
                    return self._len > 0
                for _ in self:
                    return True
                return False

            def __getitem__(self, item):
                if isinstance(item, slice):
                    if item.start is not None and item.start < 0:
                        item = slice(
                            item.start + self.get_length(), item.stop, item.step
                        )
                    if item.stop is not None and item.stop < 0:
                        item = slice(
                            item.start, item.stop + self.get_length(), item.step
                        )
                    return list(islice(self, item.start, item.stop, item.step))
                if item < 0:
                    item += self.get_length()
                return next(islice(self, item, item + 1))

            def get_length(self):
                """Returns the length of the object, perhaps by iterating over it.

                We don't want to call this method __len__ because __len__ should run in O(1) time and should not iterate over the objcet.
                """
                if self._len is not None:
                    return self._len
                for _ in iter(self):
                    pass
                return self._len

        return _TransformedIterable()

    return _callback


def compose(*transforms: tuple) -> callable:
    """Composes multiple transforms into one.

    :param transform_list: A list of transformations to apply from first to last,
    where each function accepts the document list as its only parameter.
    :return: A callable transformation function, (document list) -> (transformed document list)
    """

    def _composed(start_object, **kwargs):
        for transform in transforms:
            start_object = transform(start_object, **kwargs)
        return start_object

    return _composed
