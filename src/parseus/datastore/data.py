"Library for reading Elasticsearch indices as list-like iterables of documents."

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from numbers import Integral
from typing import List, Optional, Union

import numpy as np

from parseus.util.datetime_utils import datetime_parser


class _Scroll:
    def __init__(self, scroll_id, next_scroll_block, last_time_accessed):
        self.scroll_id = scroll_id
        self.next_scroll_block = next_scroll_block
        self.last_time_accessed = last_time_accessed
        self.buffer_from_last = []


class DSData:
    """Represents a chunked, lazy-loaded data source.

    Includes methods for iteration and indexing by integer index.
    """

    MAX_INT: int = 1 << 31
    MAX_BLOCK_SIZE = 10000
    MAX_SCROLLS = 5
    SCROLL_TIMEOUT_SECONDS = 180

    def __init__(
        self,
        ds_host,
        index: str,
        query: Union[List, None] = None,
        aggs: Union[list, dict] = None,
        composite_agg: Union[dict, None] = None,
        sort: Union[dict, list, None] = None,
        block_size: int = MAX_BLOCK_SIZE,
        es_return_fields: Union[List, None] = None,
    ):
        self.query = query
        self.ds_host = ds_host
        self.index = index
        self.aggs = aggs
        self._start_indices = np.array([0])
        self._end_indices = np.array([self.MAX_INT])
        self.sort = sort
        if aggs:
            self.data_type = "aggs"
            self._start_indices = np.array([0])
            self._end_indices = np.array([1])
        elif composite_agg:
            self.data_type = "composite_agg"
            self.aggs = deepcopy(composite_agg.get("aggs", composite_agg))
            # Assumes there is only 1 named aggregation in use
            self.agg_name = list(self.aggs.keys())[0]
            self.after_key = None
        else:  # THIS IS QUERY DATA
            self.data_type = "query"
            self.es_return_fields = es_return_fields
            self._scrolls = []
        self._block_timestamp_bounds = {}
        if block_size is None or block_size > self.MAX_BLOCK_SIZE:
            block_size = self.MAX_BLOCK_SIZE
        self._block_size = block_size

    @property
    def block_sizes_known(self) -> bool:
        """Indicates if the length of the dataset is fully known.

        This will be True for datasets of known sizes (e.g. files) and
        False for datasets that have not yet been iterated over.
        """
        return bool(len(self._end_indices) > 0 and self._end_indices[-1] < self.MAX_INT)

    def _postprocess_documents(self, documents: list) -> list:
        """Performs post-processing operations on Elasticsearch documents.

        :param documents: The Elasticsearch document list or object to process
        :return: The resulting post-processed list
        """
        docs = [
            item.get("_source", item)
            for item in documents
            if "index" not in item or len(item) != 1
        ]
        return docs

    @lru_cache(maxsize=4)
    def _get_block(self, block_index: int) -> list:
        """Defines indexing by an block (integer) index."""
        block = self._get_block_no_cache(block_index)
        return block if isinstance(block, list) else [block]

    def _get_block_post_process(self, block_index: int) -> list:
        if block_index in self._block_timestamp_bounds and not any(
            self._block_timestamp_bounds[block_index]
        ):
            # we already know this block is empty
            return self._postprocess_documents([])
        block = self._get_block(block_index)
        block = self._postprocess_documents(block)
        if not block:
            self._block_timestamp_bounds[block_index] = (None, None)
        else:
            self._block_timestamp_bounds[block_index] = (
                min(map(lambda doc: doc.get("@timestamp", None) or "X", block)),
                max(map(lambda doc: doc.get("@timestamp", None) or "", block)),
            )

        return block

    def _get_block_timestamp_bounds(self, block_index: int) -> list:
        if block_index not in self._block_timestamp_bounds:
            self._get_block_post_process(block_index)

        return self._block_timestamp_bounds[block_index]

    @lru_cache()
    def _document_index_to_block(self, index: int) -> list:
        assert index >= 0  # we only expect positive indices here
        if not self.block_sizes_known:
            # we don't know the sequence length yet.
            # load blocks until this index becomes solidified in a block
            while not self.block_sizes_known and (
                len(self._end_indices) == 1 or self._end_indices[-2] <= index
            ):
                self._get_block_post_process(len(self._end_indices) - 1)

        return np.searchsorted(self._start_indices, index, side="right") - 1

    def __getitem__(self, item):
        if isinstance(item, slice):
            # functionality removed
            raise TypeError("Slices are not supported on this object type.")

        if not isinstance(item, Integral):
            raise TypeError(
                "You must either pass a specific index, a slice of indices, or a slice of string "
                "timestamps or datetime objects"
            )

        # just return the documents at one timestamp
        if item < 0:
            item += len(self)
            if item < 0:
                raise IndexError("Attempting to index an empty data object")

        block_index = self._document_index_to_block(item)
        return self._get_block_post_process(block_index)[
            item - self._start_indices[block_index]
        ]

    def __iter__(self) -> dict:
        next_block = 0
        while not self.block_sizes_known or (
            self.block_sizes_known and next_block < len(self._start_indices)
        ):
            yield from self._get_block_post_process(next_block)
            next_block += 1

    def __len__(self) -> int:
        if not self.block_sizes_known:
            # since we don't know how long this sequence is,
            # iterate over it (unfortunately...)
            next_block = 0
            while (
                next_block < len(self._start_indices)
                and self._start_indices[next_block] < self._end_indices[next_block]
            ):
                self._get_block_post_process(next_block)
                next_block += 1

        return self._end_indices[-1]

    def __bool__(self) -> bool:
        if not self.block_sizes_known:
            for _ in self:
                return True

            return False

        return self._end_indices.size > 0 and bool(self._end_indices[-1] > 0)

    @lru_cache()
    def start_timestamp(self) -> datetime:
        """Returns the first timestamp in this dataset."""
        if 0 in self._block_timestamp_bounds:
            # we've already established the bounds for the first block, so just return that
            return datetime_parser(self._block_timestamp_bounds[0][0])
        try:
            return datetime_parser(self[0]["@timestamp"])
        except IndexError:
            # there must not be any documents
            return None

    @lru_cache()
    def end_timestamp(self) -> datetime:
        """Returns the last timestamp in this dataset."""
        if self.block_sizes_known:
            if not self:
                # there aren't any documents
                return None
            # attempt to find the end timestamp from the block timestamp bounds index
            for block_index in range(len(self._end_indices) - 1, 0, -1):
                if block_index not in self._block_timestamp_bounds:
                    # we haven't iterated this far yet
                    break
                if self._block_timestamp_bounds[block_index][1] is not None:
                    # there are timestamps in this block
                    return datetime_parser(self._block_timestamp_bounds[block_index][1])
        # we couldn't find it from the timestamp bounds.
        # this method will work but may be slow
        try:
            return datetime_parser(self[-1]["@timestamp"])
        except IndexError:
            # there must not be any documents
            return None

    def _get_scroll_from(self, next_block_index) -> Optional[_Scroll]:
        matches = [
            item for item in self._scrolls if item.next_scroll_block == next_block_index
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda x: x.last_time_accessed, reverse=True)[0]

    def _clear_scroll_safe(self, scroll_id) -> None:
        """Best-effort release of a scroll context on the datastore.

        Never raises: the scroll may already have expired or been cleared
        server-side, and a cleanup failure must not fail the caller's query.
        """
        if not scroll_id:
            return
        try:
            self.ds_host.clear_scroll(scroll_id=scroll_id)
        except Exception:
            pass

    def _retire_scroll(self, scroll: "_Scroll") -> None:
        """Release a scroll's server-side context and drop its bookkeeping.

        Called as soon as a scroll is known to be exhausted (or expired)
        instead of waiting for it to time out on its own. Without this,
        every query (e.g. an alerts-page refresh) leaves its scroll context
        open on the datastore for the full ``SCROLL_TIMEOUT_SECONDS``, and
        repeated/concurrent queries can exhaust the datastore's open-scroll
        limit (Elasticsearch/OpenSearch default ``search.max_open_scroll_context``),
        surfacing as "too many scroll contexts" errors to callers.
        """
        self._clear_scroll_safe(scroll.scroll_id)
        if scroll in self._scrolls:
            self._scrolls.remove(scroll)

    def close(self) -> None:
        """Release any scroll contexts still held open by this object.

        Safe to call multiple times. Callers that only consume part of a
        query's results (e.g. break out of a loop early) should call this
        explicitly; fully-exhausted iteration already retires its scroll via
        :meth:`_retire_scroll`. :meth:`__del__` also calls this as a
        best-effort safety net.
        """
        if self.data_type != "query":
            return
        for scroll in list(self._scrolls):
            self._clear_scroll_safe(scroll.scroll_id)
        self._scrolls = []

    def __enter__(self) -> "DSData":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            # __del__ must never raise during interpreter teardown/GC.
            pass

    def _prune_expired_scrolls(self):
        # prune scrolls X seconds before they actually expire, so that way we know if
        # continue_scroll() function failed it's because the data is done
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=self.SCROLL_TIMEOUT_SECONDS
        )
        expiring = [item for item in self._scrolls if item.last_time_accessed < cutoff]
        for item in expiring:
            # These scrolls are about to time out server-side anyway; clear
            # them explicitly instead of relying on the datastore to do it,
            # since an abandoned (never-exhausted) scroll otherwise keeps its
            # context open for the full TTL.
            self._clear_scroll_safe(item.scroll_id)
        self._scrolls = [item for item in self._scrolls if item not in expiring]

    def _get_block_no_cache(self, block_index: int):
        if self.data_type == "query":
            self._prune_expired_scrolls()
            page_contents = None
            previous_scroll_id = None
            if block_index == 0 and len(self._scrolls) < self.MAX_SCROLLS:
                scroll_id, page_contents = self.ds_host.start_scroll(
                    self.index,
                    size=self._block_size,
                    timeout=f"{self.SCROLL_TIMEOUT_SECONDS}s",
                    query=self.query,
                    sort=self.sort,
                    return_fields=self.es_return_fields,
                )
                this_scroll = _Scroll(scroll_id, 1, datetime.now(timezone.utc))
                self._scrolls.append(this_scroll)
            else:
                this_scroll = self._get_scroll_from(block_index)
                if this_scroll:
                    previous_scroll_id = this_scroll.scroll_id
                    scroll_id, page_contents = self.ds_host.continue_scroll(
                        this_scroll.scroll_id, timeout=f"{self.SCROLL_TIMEOUT_SECONDS}s"
                    )
                    this_scroll.next_scroll_block = block_index + 1
            if this_scroll:
                # we found a scroll that could pull this block.
                # filter out all timestamps besides the last one
                at_end = not page_contents
                page_contents = this_scroll.buffer_from_last + page_contents
                if page_contents:
                    last_timestamp = page_contents[-1].get("@timestamp", None)
                    sub_page_contents = [
                        doc
                        for doc in page_contents
                        if at_end
                        or (doc.get("@timestamp", None) or "") < (last_timestamp or "")
                    ]
                else:
                    sub_page_contents = []
                to_return = sub_page_contents
                # update the scroll buffer
                this_scroll.buffer_from_last = page_contents[len(sub_page_contents) :]
                this_scroll.last_time_accessed = datetime.now(timezone.utc)
                # Keep whichever scroll id is still valid: a fresh one from
                # this call, or (if the datastore reports no more hits, which
                # returns a None scroll id) the last one we actually used, so
                # it can still be cleared below.
                this_scroll.scroll_id = (
                    scroll_id if scroll_id is not None else previous_scroll_id
                )
                # if this is too long (e.g. the index changed),
                # trim its length to what we were expecting
                max_result_size = (
                    self._end_indices[block_index] - self._start_indices[block_index]
                )
                if len(to_return) > max_result_size:
                    to_return = to_return[:max_result_size]
                # update the start/end indices
                assert len(self._start_indices) >= block_index + 1
                if len(self._start_indices) == block_index + 1:
                    self._end_indices[block_index] = self._start_indices[
                        block_index
                    ] + len(to_return)
                    if not at_end:
                        self._start_indices = np.append(
                            self._start_indices, self._end_indices[-1]
                        )
                        self._end_indices = np.append(self._end_indices, self.MAX_INT)
                assert (
                    len(to_return)
                    == self._end_indices[block_index] - self._start_indices[block_index]
                )
                if at_end:
                    # Nothing left to scroll: release the context now rather
                    # than leaving it open for SCROLL_TIMEOUT_SECONDS.
                    self._retire_scroll(this_scroll)
                return to_return
            # if we couldn't get the page contents from a scroll
            # but we know the timestamp bounds for this block, use those
            if block_index in self._block_timestamp_bounds:
                # check if the block is empty
                if set(self._block_timestamp_bounds[block_index]) == {None}:
                    return []

                # build the query for this section
                start = self._block_timestamp_bounds[block_index][0]
                end = self._block_timestamp_bounds[block_index][1]
                block_time_query = {
                    "range": {
                        "@timestamp": {
                            "gte": datetime_parser(start),
                            "lte": datetime_parser(end),
                        }
                    }
                }
                query = deepcopy(self.query)
                if query is None:
                    query = block_time_query
                else:
                    if "bool" not in query:
                        query = {"bool": {"must": [query, block_time_query]}}
                    else:
                        for clause in query["bool"]:
                            for index, subquery in enumerate(query["bool"][clause]):
                                if "range" in subquery:
                                    query["bool"][clause][index] = block_time_query

                # get the results
                return list(
                    self.ds_host.get_all_entries(
                        self.index, query=query, sort=self.sort
                    )
                )
            # need to scroll up until this block
            for i in range(block_index):
                # discard every block's contents - we just need to know the length
                self._get_block_no_cache(i)
            return self._get_block(block_index)  # try again
        if self.data_type == "aggs":
            # get_aggs returns None when the index does not exist; treat that
            # as "no data" (like the plain-query branch does) instead of crashing.
            resp = self.ds_host.get_aggs(self.index, self.aggs, self.query) or {}
            aggregate_data = resp.get("aggregations", {})
            return aggregate_data
        elif self.data_type == "composite_agg":
            if self.after_key is not None:
                self.aggs[self.agg_name]["composite"]["after"] = self.after_key
            # None means the index does not exist: no buckets, not an error.
            resp = self.ds_host.get_aggs(self.index, self.aggs, self.query) or {}
            to_return = (
                resp.get("aggregations", {}).get(self.agg_name, {}).get("buckets", [])
            )
            self.after_key = (
                resp.get("aggregations", {})
                .get(self.agg_name, {})
                .get("after_key", None)
            )
            # if this is too long (e.g. the index changed),
            # trim its length to what we were expecting
            max_result_size = (
                self._end_indices[block_index] - self._start_indices[block_index]
            )
            if len(to_return) > max_result_size:
                to_return = to_return[:max_result_size]
            # update the start/end indices
            if len(self._start_indices) == block_index + 1:
                self._end_indices[block_index] = self._start_indices[block_index] + len(
                    to_return
                )
                if len(to_return) > 0:
                    self._start_indices = np.append(
                        self._start_indices, self._end_indices[-1]
                    )
                    self._end_indices = np.append(self._end_indices, self.MAX_INT)
            return to_return
